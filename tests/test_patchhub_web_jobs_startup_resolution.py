# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config
from patchhub.models import JobRecord
from patchhub.web_jobs_backup import WebJobsBackupSettings, create_verified_backup
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


def _load_core_cfg() -> object:
    cfg_path = Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    return load_config(cfg_path)


def _write_backup_cfg(repo_root: Path) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "[web_jobs_backup]",
                'destination_template = "artifacts/backups/web_jobs_backup_{timestamp}.sqlite3"',
                'trigger_policy = "manual"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_db(repo_root: Path, *, job_id: str) -> tuple[Path, WebJobsDatabase]:
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id=job_id,
            created_utc="2026-03-10T12:00:00Z",
            mode="patch",
            issue_id="515",
            commit_summary="startup resolution",
            patch_basename="issue_515_v1.zip",
            raw_command="python3 scripts/am_patch.py 515",
            canonical_command=["python3", "scripts/am_patch.py", "515"],
            status="success",
        )
    )
    db.append_log_line(job_id, "alpha")
    db.append_event_line(job_id, '{"type":"status","event":"done"}')
    return patches_root, db


@pytest.mark.asyncio
async def test_async_core_defers_backend_runtime_until_startup(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    assert core.web_jobs_db is None
    assert core.virtual_jobs_fs is None
    assert core.queue_block_reason() == "Backend mode selection is not finished"

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "db_primary"
        assert core.web_jobs_db is not None
        assert core.virtual_jobs_fs is not None
        assert core.queue_block_reason() is None
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_async_core_startup_restores_corrupted_main_db_before_runtime_wiring(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root)
    patches_root, db = _seed_db(repo_root, job_id="job-515-startup")
    backup = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=WebJobsBackupSettings(
            enabled=True,
            destination_template="artifacts/backups/web_jobs_backup_{timestamp}.sqlite3",
            retain_count=5,
            verify_after_backup=True,
            trigger_policy="manual",
            restore_source_preference=("latest_backup",),
        ),
    )
    db.cfg.db_path.write_text("not-a-sqlite-db", encoding="utf-8")

    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())
    assert core.web_jobs_db is None

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "db_primary"
        assert core.web_jobs_db is not None
        assert core.backend_mode_state.last_recovery["recovery_action"] == (
            "restored_from_verified_backup"
        )
        assert core.backend_mode_state.last_recovery["used_backup_path"] == str(backup.path)
        restored = core.web_jobs_db.load_job_record("job-515-startup")
        assert restored is not None
        assert restored.status == "success"
    finally:
        await core.shutdown()
