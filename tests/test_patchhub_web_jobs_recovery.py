# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_backup import WebJobsBackupSettings, create_verified_backup
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_recovery import (
    begin_startup_session,
    mark_shutdown_clean,
    read_runtime_state,
    record_verified_backup,
    resolve_web_jobs_backend,
)


def _seed_db(repo_root: Path) -> tuple[Path, WebJobsDatabase]:
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id="job-515-recovery",
            created_utc="2026-03-10T10:30:00Z",
            mode="patch",
            issue_id="515",
            commit_summary="Recovery seed",
            patch_basename="issue_515_v1.zip",
            raw_command="python3 scripts/am_patch.py 515",
            canonical_command=["python3", "scripts/am_patch.py", "515"],
            status="success",
        )
    )
    db.append_log_line("job-515-recovery", "alpha")
    db.append_event_line("job-515-recovery", '{"type":"status","event":"done"}')
    return patches_root, db


def test_recovery_initializes_new_db_primary_when_main_db_is_absent(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)

    resolution = resolve_web_jobs_backend(
        repo_root=repo_root,
        patches_root=patches_root,
        jobs_root=patches_root / "artifacts" / "web_jobs",
        db_cfg=cfg,
    )

    assert resolution.mode == "db_primary"
    assert resolution.job_db is not None
    assert resolution.recovery["recovery_action"] == "initialized_new_main_db"
    assert cfg.db_path.is_file()

    mark_shutdown_clean(patches_root, resolution.session_id, resolution.recovery)
    marker = json.loads(
        (patches_root / "artifacts" / "web_jobs_runtime_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert marker["state"] == "clean"


def test_recovery_restores_from_latest_verified_backup_after_unclean_shutdown(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root, db = _seed_db(repo_root)
    backup = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=WebJobsBackupSettings(
            enabled=True,
            destination_template="artifacts/web_jobs_backup_{timestamp}.sqlite3",
            retain_count=5,
            verify_after_backup=True,
            trigger_policy="manual",
            restore_source_preference=("latest_backup",),
        ),
    )
    marker_path = patches_root / "artifacts" / "web_jobs_runtime_state.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text('{"state":"dirty","session_id":"prev"}\n', encoding="utf-8")
    db.cfg.db_path.write_text("not-a-sqlite-db", encoding="utf-8")

    resolution = resolve_web_jobs_backend(
        repo_root=repo_root,
        patches_root=patches_root,
        jobs_root=patches_root / "artifacts" / "web_jobs",
        db_cfg=db.cfg,
    )

    assert resolution.mode == "db_primary"
    assert resolution.job_db is not None
    assert resolution.recovery["recovery_action"] == "restored_from_verified_backup"
    assert resolution.recovery["used_backup_path"] == str(backup.path)
    restored = resolution.job_db.load_job_record("job-515-recovery")
    assert restored is not None
    assert restored.status == "success"


def test_runtime_state_preserves_last_verified_backup_across_lifecycle(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    backup_path = patches_root / "artifacts" / "backups" / "verified.sqlite3"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text("backup", encoding="utf-8")

    record_verified_backup(patches_root, backup_path=backup_path)
    initial = read_runtime_state(patches_root)
    session_id, previous_clean, _, _ = begin_startup_session(patches_root)
    startup_state = read_runtime_state(patches_root)

    assert previous_clean is True
    for key in (
        "last_verified_backup_utc",
        "last_verified_backup_path",
        "last_verified_backup_status",
    ):
        assert startup_state[key] == initial[key]

    mark_shutdown_clean(patches_root, session_id, {"recovery_action": "none"})
    shutdown_state = read_runtime_state(patches_root)

    assert shutdown_state["state"] == "clean"
    for key in (
        "last_verified_backup_utc",
        "last_verified_backup_path",
        "last_verified_backup_status",
    ):
        assert shutdown_state[key] == initial[key]
