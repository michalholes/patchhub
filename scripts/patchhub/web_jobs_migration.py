from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Protocol, cast

from .models import (
    JobRecord,
    LegacyJobSnapshot,
    WebJobsDbConfig,
    coerce_job_mode,
    coerce_job_status,
)
from .web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from .web_jobs_legacy_fs import iter_legacy_job_dirs, read_legacy_job_snapshot
from .web_jobs_recovery import record_verified_backup


class MigrationCliArgs(Protocol):
    command: str
    source: str
    dest: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _patches_root(repo_root: Path) -> Path:
    return repo_root / "patches"


def _jobs_root(repo_root: Path) -> Path:
    return _patches_root(repo_root) / "artifacts" / "web_jobs"


def _obj_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(cast(list[object], value))
    return []


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value or default))
    except Exception:
        return default


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except Exception:
        return None


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _build_cfg(repo_root: Path) -> WebJobsDbConfig:
    return load_web_jobs_db_config(repo_root, _patches_root(repo_root))


def _build_db(repo_root: Path) -> WebJobsDatabase:
    cfg = _build_cfg(repo_root)
    return WebJobsDatabase(cfg)


def _snapshot_to_job(snapshot: LegacyJobSnapshot) -> JobRecord:
    raw: dict[str, object] = dict(snapshot.job_json) if snapshot.job_json is not None else {}
    patch_basename = _as_optional_str(raw.get("patch_basename"))
    return JobRecord(
        job_id=str(raw.get("job_id", snapshot.job_id)),
        created_utc=str(raw.get("created_utc", "")),
        created_unix_ms=_as_int(raw.get("created_unix_ms", 0), 0),
        mode=coerce_job_mode(raw.get("mode", "patch")),
        issue_id=str(raw.get("issue_id", "")),
        commit_summary=str(raw.get("commit_summary", "")),
        patch_basename=patch_basename,
        raw_command=str(raw.get("raw_command", "")),
        canonical_command=[str(item) for item in _obj_list(raw.get("canonical_command"))],
        status=coerce_job_status(raw.get("status", "unknown")),
        started_utc=_as_optional_str(raw.get("started_utc")),
        ended_utc=_as_optional_str(raw.get("ended_utc")),
        return_code=_as_optional_int(raw.get("return_code")),
        error=_as_optional_str(raw.get("error")),
        cancel_requested_utc=_as_optional_str(raw.get("cancel_requested_utc")),
        cancel_ack_utc=_as_optional_str(raw.get("cancel_ack_utc")),
        cancel_source=_as_optional_str(raw.get("cancel_source")),
        original_patch_path=_as_optional_str(raw.get("original_patch_path")),
        effective_patch_path=_as_optional_str(raw.get("effective_patch_path")),
        effective_patch_kind=_as_optional_str(raw.get("effective_patch_kind")),
        selected_patch_entries=[str(x) for x in _obj_list(raw.get("selected_patch_entries"))],
        selected_repo_paths=[str(x) for x in _obj_list(raw.get("selected_repo_paths"))],
        applied_files=[str(x) for x in _obj_list(raw.get("applied_files"))],
        applied_files_source=str(raw.get("applied_files_source", "unavailable")),
        last_log_seq=_as_int(raw.get("last_log_seq", 0), 0),
        last_event_seq=_as_int(raw.get("last_event_seq", 0), 0),
        row_rev=_as_int(raw.get("row_rev", 0), 0),
    )


def _scan(repo_root: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for job_dir in iter_legacy_job_dirs(_jobs_root(repo_root)):
        snapshot = read_legacy_job_snapshot(job_dir)
        items.append(
            {
                "job_id": snapshot.job_id,
                "importable": snapshot.job_json is not None,
                "has_log": bool(snapshot.log_lines),
                "has_events": bool(snapshot.event_lines),
            }
        )
    return items


def _migrate(repo_root: Path) -> list[str]:
    db = _build_db(repo_root)
    imported: list[str] = []
    for job_dir in iter_legacy_job_dirs(_jobs_root(repo_root)):
        snapshot = read_legacy_job_snapshot(job_dir)
        if snapshot.job_json is None:
            continue
        job = _snapshot_to_job(snapshot)
        db.replace_job_history(
            job,
            log_lines=snapshot.log_lines,
            event_lines=snapshot.event_lines,
        )
        imported.append(job.job_id)
    return imported


def _resolve_config_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path or "").strip())
    if not str(path):
        return _build_cfg(repo_root).db_path
    if path.is_absolute():
        return path
    return (_patches_root(repo_root) / path).resolve()


def _latest_backup_path(repo_root: Path) -> Path | None:
    cfg = _build_cfg(repo_root)
    template = str(cfg.backup_destination_template or "").strip()
    if not template:
        return None
    candidate = _resolve_config_path(repo_root, template.format(timestamp="latest"))
    if "{timestamp}" not in template:
        return candidate if candidate.is_file() else None
    pattern = template.replace("{timestamp}", "*")
    parent = _resolve_config_path(repo_root, pattern).parent
    name_glob = Path(pattern).name
    matches = [path for path in parent.glob(name_glob) if path.is_file()]
    if not matches:
        return None

    def _path_mtime_key(path: Path) -> int:
        return int(path.stat().st_mtime_ns)

    matches.sort(key=_path_mtime_key, reverse=True)
    return matches[0]


def _resolve_restore_source(repo_root: Path, source: Path | None) -> Path:
    cfg = _build_cfg(repo_root)
    explicit = None
    if source is not None and str(source).strip():
        explicit = source if source.is_absolute() else (repo_root / source).resolve()
    for item in cfg.recovery_restore_source_preference:
        if item == "explicit" and explicit is not None and explicit.is_file():
            return explicit
        if item == "latest_backup":
            backup = _latest_backup_path(repo_root)
            if backup is not None:
                return backup
        if item == "main_db" and cfg.db_path.is_file():
            return cfg.db_path
    if explicit is not None:
        return explicit
    raise FileNotFoundError("No configured web_jobs restore source is available")


def _verify(repo_root: Path) -> list[dict[str, object]]:
    db = _build_db(repo_root)
    out: list[dict[str, object]] = []
    for job_dir in iter_legacy_job_dirs(_jobs_root(repo_root)):
        snapshot = read_legacy_job_snapshot(job_dir)
        expected_job = (
            _snapshot_to_job(snapshot).to_json() if snapshot.job_json is not None else None
        )
        db_job = db.load_job_json(snapshot.job_id)
        db_log = db.read_full_log(snapshot.job_id)
        db_events = db.legacy_event_text(snapshot.job_id)
        if expected_job is not None:
            expected_job["last_log_seq"] = len(snapshot.log_lines)
            expected_job["last_event_seq"] = len(snapshot.event_lines)
            expected_job.setdefault("commit_message", None)
            expected_job.setdefault("zip_target_repo", None)
            expected_job.setdefault("selected_target_repo", None)
            expected_job.setdefault("effective_runner_target_repo", None)
            expected_job.setdefault("run_start_sha", None)
            expected_job.setdefault("run_end_sha", None)
            expected_job.setdefault("revert_source_job_id", None)
            expected_job.setdefault("rollback_source_job_id", None)
            expected_job.setdefault("rollback_scope_manifest_rel_path", None)
            expected_job.setdefault("rollback_scope_manifest_hash", None)
            expected_job.setdefault("rollback_authority_kind", None)
            expected_job.setdefault("rollback_authority_source_ref", None)
            if db_job is not None and "row_rev" in db_job:
                expected_job["row_rev"] = _as_int(db_job.get("row_rev", 0), 0)
        ok = (
            expected_job is not None
            and db_job == expected_job
            and db_log.splitlines() == snapshot.log_lines
            and db_events.splitlines() == snapshot.event_lines
        )
        out.append({"job_id": snapshot.job_id, "ok": ok})
    return out


def migrate_legacy_jobs(repo_root: Path) -> list[str]:
    return _migrate(repo_root)


def verify_legacy_jobs(repo_root: Path) -> list[dict[str, object]]:
    return _verify(repo_root)


def _cleanup(repo_root: Path) -> list[str]:
    cfg = _build_cfg(repo_root)
    if not cfg.cleanup_enabled:
        raise RuntimeError("web_jobs cleanup is disabled by config")
    removed: list[str] = []
    for item in _verify(repo_root):
        if not bool(item.get("ok", False)):
            continue
        job_id = str(item.get("job_id", "")).strip()
        if not job_id:
            continue
        job_dir = _jobs_root(repo_root) / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
            removed.append(job_id)
    return removed


def _backup(repo_root: Path) -> str:
    db = _build_db(repo_root)
    backup_path = db.create_backup()
    record_verified_backup(_patches_root(repo_root), backup_path=backup_path)
    return str(backup_path)


def _restore(repo_root: Path, source: Path | None = None) -> str:
    db = _build_db(repo_root)
    resolved = _resolve_restore_source(repo_root, source)
    db.restore_backup(resolved)
    return str(resolved)


def _export_legacy(repo_root: Path, dest: Path | None = None) -> str:
    db = _build_db(repo_root)
    target = dest or (_patches_root(repo_root) / "artifacts" / "web_jobs_export")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    db.export_legacy_tree(target)
    return str(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "scan",
            "migrate",
            "verify",
            "cleanup",
            "backup",
            "restore",
            "export_legacy",
        ],
    )
    parser.add_argument("--source", default="")
    parser.add_argument("--dest", default="")
    ns = cast(MigrationCliArgs, parser.parse_args(argv))
    command = str(ns.command)
    source_arg = str(ns.source)
    dest_arg = str(ns.dest)
    repo_root = _repo_root()
    if command == "scan":
        payload: dict[str, object] = {"items": _scan(repo_root)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if command == "migrate":
        payload = {"imported": _migrate(repo_root)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if command == "verify":
        payload = {"items": _verify(repo_root)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if command == "cleanup":
        payload = {"removed": _cleanup(repo_root)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if command == "backup":
        payload = {"backup": _backup(repo_root)}
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if command == "restore":
        source = Path(source_arg) if source_arg else None
        payload = {"restored": _restore(repo_root, source)}
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                indent=2,
            )
        )
        return 0
    if command == "export_legacy":
        target = Path(dest_arg) if dest_arg else None
        payload = {"exported": _export_legacy(repo_root, target)}
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
