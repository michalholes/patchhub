# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.models import JobRecord
from patchhub.web_jobs_backup import (
    WebJobsBackupSettings,
    create_verified_backup,
    latest_verified_backup,
)
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


@pytest.fixture
def seeded_db(tmp_path: Path) -> tuple[Path, Path, WebJobsDatabase]:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id="job-515-backup",
            created_utc="2026-03-10T10:00:00Z",
            mode="patch",
            issue_id="515",
            commit_summary="Backup seed",
            patch_basename="issue_515_v1.zip",
            raw_command="python3 scripts/am_patch.py 515",
            canonical_command=["python3", "scripts/am_patch.py", "515"],
            status="success",
        )
    )
    db.append_log_line("job-515-backup", "line-1")
    db.append_event_line("job-515-backup", '{"type":"status","event":"done"}')
    return repo_root, patches_root, db


def test_create_verified_backup_retains_only_verified_files(
    seeded_db: tuple[Path, Path, WebJobsDatabase],
) -> None:
    _repo_root, patches_root, db = seeded_db
    settings = WebJobsBackupSettings(
        enabled=True,
        destination_template="artifacts/backups/web_jobs_backup_{timestamp}.sqlite3",
        retain_count=2,
        verify_after_backup=True,
        trigger_policy="manual",
        restore_source_preference=("latest_backup",),
    )
    first = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=settings,
    )
    second = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=settings,
    )
    third = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=settings,
    )

    backups = list((patches_root / "artifacts" / "backups").glob("*.sqlite3"))
    assert first.verified is True
    assert second.verified is True
    assert third.verified is True
    assert latest_verified_backup(patches_root=patches_root, settings=settings) == third.path
    assert len(backups) == 2
    assert first.path not in backups
    assert second.path in backups
    assert third.path in backups


def test_backup_verification_failure_keeps_previous_verified_backup(
    seeded_db: tuple[Path, Path, WebJobsDatabase],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo_root, patches_root, db = seeded_db
    settings = WebJobsBackupSettings(
        enabled=True,
        destination_template="artifacts/backups/web_jobs_backup_{timestamp}.sqlite3",
        retain_count=5,
        verify_after_backup=True,
        trigger_policy="manual",
        restore_source_preference=("latest_backup",),
    )
    first = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=settings,
    )

    def _boom(path: Path) -> None:
        del path
        raise RuntimeError("forced_verify_failure")

    monkeypatch.setattr("patchhub.web_jobs_backup.verify_sqlite_backup", _boom)
    with pytest.raises(RuntimeError, match="forced_verify_failure"):
        create_verified_backup(
            db_path=db.cfg.db_path,
            patches_root=patches_root,
            settings=settings,
        )

    backups = list((patches_root / "artifacts" / "backups").glob("*.sqlite3"))
    assert backups == [first.path]
