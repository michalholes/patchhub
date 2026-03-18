from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import WebJobsDbConfig
from .web_jobs_backup import (
    WebJobsBackupSettings,
    latest_verified_backup,
    load_web_jobs_backup_settings,
    verify_sqlite_backup,
)
from .web_jobs_db import WebJobsDatabase
from .web_jobs_legacy_fs import iter_legacy_job_dirs


@dataclass(frozen=True)
class WebJobsRecoverySettings:
    restore_source_preference: tuple[str, ...]


@dataclass(frozen=True)
class WebJobsRecoveryResolution:
    mode: str
    job_db: WebJobsDatabase | None
    session_id: str
    recovery: dict[str, Any]


_REQUIRED_TABLES = (
    "web_jobs",
    "web_job_log_lines",
    "web_job_event_lines",
    "web_jobs_meta",
)


def load_web_jobs_recovery_settings(repo_root: Path) -> WebJobsRecoverySettings:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, Any] = {}
    if cfg_path.is_file():
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    recovery_raw = raw.get("web_jobs_recovery", {})
    raw_pref = recovery_raw.get("restore_source_preference")
    if isinstance(raw_pref, list | tuple):
        pref = tuple(str(item).strip() for item in raw_pref if str(item).strip())
    else:
        pref = ("explicit", "latest_backup", "main_db")
    return WebJobsRecoverySettings(restore_source_preference=pref or ("latest_backup",))


_BACKUP_STATE_KEYS = (
    "last_verified_backup_utc",
    "last_verified_backup_path",
    "last_verified_backup_status",
)


def runtime_state_path(patches_root: Path) -> Path:
    return patches_root / "artifacts" / "web_jobs_runtime_state.json"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_runtime_state_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_runtime_state_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def read_runtime_state(patches_root: Path) -> dict[str, Any]:
    return read_runtime_state_file(runtime_state_path(patches_root))


def _carry_backup_state(payload: dict[str, Any]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key in _BACKUP_STATE_KEYS:
        if key in payload:
            kept[key] = payload[key]
    return kept


def record_verified_backup(
    patches_root: Path,
    *,
    backup_path: Path,
    status: str = "verified",
) -> dict[str, Any]:
    path = runtime_state_path(patches_root)
    payload = read_runtime_state_file(path)
    payload.update(
        {
            "last_verified_backup_utc": _utc_now(),
            "last_verified_backup_path": str(backup_path),
            "last_verified_backup_status": str(status),
        }
    )
    write_runtime_state_file(path, payload)
    return payload


def begin_startup_session(patches_root: Path) -> tuple[str, bool, Path, dict[str, Any]]:
    marker_path = runtime_state_path(patches_root)
    previous = read_runtime_state_file(marker_path)
    previous_clean = str(previous.get("state", "clean")) == "clean"
    session_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-pid{os.getpid()}"
    current = {
        **_carry_backup_state(previous),
        "state": "dirty",
        "session_id": session_id,
        "started_utc": _utc_now(),
        "previous": previous,
    }
    write_runtime_state_file(marker_path, current)
    return session_id, previous_clean, marker_path, previous


def mark_shutdown_clean(patches_root: Path, session_id: str, recovery: dict[str, Any]) -> None:
    path = runtime_state_path(patches_root)
    previous = read_runtime_state_file(path)
    payload = {
        **_carry_backup_state(previous),
        "state": "clean",
        "session_id": str(session_id),
        "ended_utc": _utc_now(),
        "last_recovery": dict(recovery),
    }
    write_runtime_state_file(path, payload)


def _validate_db_path(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        with sqlite3.connect(str(path)) as conn:
            rows = conn.execute("PRAGMA quick_check").fetchall()
            if not rows or any(str(row[0]) != "ok" for row in rows):
                return False, "quick_check_failed"
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
    except sqlite3.DatabaseError as exc:
        return False, f"database_error:{type(exc).__name__}:{exc}"
    except OSError as exc:
        return False, f"os_error:{type(exc).__name__}:{exc}"
    missing = [name for name in _REQUIRED_TABLES if name not in tables]
    if missing:
        return False, "missing_required_tables:" + ",".join(missing)
    return True, "ok"


def _build_job_db(cfg: WebJobsDbConfig) -> WebJobsDatabase:
    db = WebJobsDatabase(cfg)
    db.jobs_signature()
    return db


def _restore_main_db_from_backup(db_cfg: WebJobsDbConfig, source: Path) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=db_cfg.db_path.name + ".restore.",
        dir=str(db_cfg.db_path.parent),
    )
    Path(tmp_name).unlink(missing_ok=True)
    Path(tmp_name).parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, tmp_name)
        for suffix in ("-wal", "-shm"):
            Path(str(db_cfg.db_path) + suffix).unlink(missing_ok=True)
        Path(tmp_name).replace(db_cfg.db_path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def _count_legacy_jobs(jobs_root: Path) -> int:
    return len(iter_legacy_job_dirs(jobs_root))


def _copy_candidate_for_export(source_path: Path, db_cfg: WebJobsDbConfig) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="patchhub-web-jobs-export-"))
    copied = tmp_dir / db_cfg.db_path.name
    try:
        with sqlite3.connect(str(source_path)) as src_conn:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            with sqlite3.connect(str(copied)) as dst_conn:
                src_conn.backup(dst_conn)
    except Exception:
        shutil.copy2(source_path, copied)
    return copied


def _verify_export_complete(export_root: Path, expected_job_ids: list[str]) -> None:
    exported_ids = sorted(path.name for path in iter_legacy_job_dirs(export_root))
    if exported_ids != sorted(expected_job_ids):
        raise RuntimeError("legacy_export_incomplete")
    for job_id in expected_job_ids:
        job_dir = export_root / job_id
        if not (job_dir / "job.json").is_file():
            raise RuntimeError("legacy_export_missing_job_json")
        if not (job_dir / "runner.log").is_file():
            raise RuntimeError("legacy_export_missing_runner_log")
        if not list(job_dir.glob("*.jsonl")):
            raise RuntimeError("legacy_export_missing_jsonl")


def _export_candidate_to_legacy(
    *,
    source_path: Path,
    db_cfg: WebJobsDbConfig,
    jobs_root: Path,
) -> tuple[bool, str, int]:
    copied = _copy_candidate_for_export(source_path, db_cfg)
    export_root = Path(tempfile.mkdtemp(prefix="patchhub-web-jobs-legacy-"))
    try:
        candidate_cfg = replace(db_cfg, db_path=copied)
        db = _build_job_db(candidate_cfg)
        expected_job_ids = db.list_job_ids(limit=1_000_000)
        db.export_legacy_tree(export_root)
        _verify_export_complete(export_root, expected_job_ids)
        backup_jobs_root = jobs_root.with_name(jobs_root.name + ".pre_file_emergency")
        backup_jobs_root.unlink(missing_ok=True) if backup_jobs_root.is_file() else None
        if backup_jobs_root.exists():
            shutil.rmtree(backup_jobs_root)
        if jobs_root.exists():
            jobs_root.replace(backup_jobs_root)
        export_root.replace(jobs_root)
        if backup_jobs_root.exists():
            shutil.rmtree(backup_jobs_root)
        return True, str(source_path), len(expected_job_ids)
    except Exception as exc:
        shutil.rmtree(export_root, ignore_errors=True)
        return False, f"{type(exc).__name__}:{exc}", 0
    finally:
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(copied.parent, ignore_errors=True)


def resolve_web_jobs_backend(
    *,
    repo_root: Path,
    patches_root: Path,
    jobs_root: Path,
    db_cfg: WebJobsDbConfig,
) -> WebJobsRecoveryResolution:
    recovery_settings = load_web_jobs_recovery_settings(repo_root)
    backup_settings: WebJobsBackupSettings = load_web_jobs_backup_settings(
        repo_root,
        patches_root,
        db_cfg,
    )
    session_id, previous_clean, marker_path, _previous = begin_startup_session(patches_root)
    recovery: dict[str, Any] = {
        "status": "resolving",
        "marker_path": str(marker_path),
        "session_id": session_id,
        "previous_shutdown_clean": previous_clean,
        "selected_mode": "resolving",
        "main_db_path": str(db_cfg.db_path),
        "used_backup_path": None,
        "exported_jobs": 0,
        "recovery_action": "none",
        "restore_source_preference": list(recovery_settings.restore_source_preference),
    }

    if not db_cfg.db_path.exists() and _count_legacy_jobs(jobs_root) == 0:
        job_db = _build_job_db(db_cfg)
        recovery["status"] = "ok"
        recovery["selected_mode"] = "db_primary"
        recovery["recovery_action"] = "initialized_new_main_db"
        return WebJobsRecoveryResolution(
            mode="db_primary",
            job_db=job_db,
            session_id=session_id,
            recovery=recovery,
        )

    main_ok, main_reason = _validate_db_path(db_cfg.db_path)
    recovery["main_db_validation"] = main_reason
    if main_ok:
        job_db = _build_job_db(db_cfg)
        recovery["status"] = "ok"
        recovery["selected_mode"] = "db_primary"
        recovery["recovery_action"] = (
            "clean_start_db_primary" if previous_clean else "validated_after_unclean_shutdown"
        )
        return WebJobsRecoveryResolution(
            mode="db_primary",
            job_db=job_db,
            session_id=session_id,
            recovery=recovery,
        )

    latest_backup = latest_verified_backup(patches_root=patches_root, settings=backup_settings)
    if latest_backup is not None:
        try:
            verify_sqlite_backup(latest_backup)
            _restore_main_db_from_backup(db_cfg, latest_backup)
            job_db = _build_job_db(db_cfg)
            recovery["status"] = "ok"
            recovery["selected_mode"] = "db_primary"
            recovery["used_backup_path"] = str(latest_backup)
            recovery["recovery_action"] = "restored_from_verified_backup"
            return WebJobsRecoveryResolution(
                mode="db_primary",
                job_db=job_db,
                session_id=session_id,
                recovery=recovery,
            )
        except Exception as exc:
            recovery["backup_restore_error"] = f"{type(exc).__name__}:{exc}"

    export_candidates = [db_cfg.db_path]
    if latest_backup is not None:
        export_candidates.append(latest_backup)
    for candidate in export_candidates:
        if not candidate.exists():
            continue
        ok, source_info, exported_jobs = _export_candidate_to_legacy(
            source_path=candidate,
            db_cfg=db_cfg,
            jobs_root=jobs_root,
        )
        if ok:
            recovery["status"] = "ok"
            recovery["selected_mode"] = "file_emergency"
            recovery["recovery_action"] = "exported_legacy_and_switched_to_file_emergency"
            recovery["used_backup_path"] = (
                str(latest_backup) if candidate == latest_backup else None
            )
            recovery["fallback_export_source"] = source_info
            recovery["exported_jobs"] = exported_jobs
            return WebJobsRecoveryResolution(
                mode="file_emergency",
                job_db=None,
                session_id=session_id,
                recovery=recovery,
            )
        recovery.setdefault("fallback_export_errors", []).append(source_info)

    if _count_legacy_jobs(jobs_root) > 0:
        recovery["status"] = "ok"
        recovery["selected_mode"] = "file_emergency"
        recovery["recovery_action"] = "using_existing_legacy_tree"
        return WebJobsRecoveryResolution(
            mode="file_emergency",
            job_db=None,
            session_id=session_id,
            recovery=recovery,
        )

    recovery["status"] = "failed"
    recovery["selected_mode"] = "resolving"
    recovery["recovery_action"] = "startup_failed"
    raise RuntimeError(json.dumps(recovery, ensure_ascii=True, sort_keys=True))
