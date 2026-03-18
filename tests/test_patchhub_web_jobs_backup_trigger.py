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


def _write_backup_cfg(repo_root: Path, *, trigger_policy: str) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "[web_jobs_backup]",
                'destination_template = "artifacts/backups/web_jobs_backup_{timestamp}.sqlite3"',
                "retain_count = 10",
                "verify_after_write = true",
                f'trigger_policy = "{trigger_policy}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _load_core_cfg() -> object:
    cfg_path = Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    return load_config(cfg_path)


def _build_db(repo_root: Path) -> tuple[Path, WebJobsDatabase]:
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    return patches_root, db


def _seed_terminal_job(db: WebJobsDatabase, *, job_id: str) -> None:
    db.upsert_job(
        JobRecord(
            job_id=job_id,
            created_utc="2026-03-10T12:30:00Z",
            mode="patch",
            issue_id="515",
            commit_summary="backup trigger",
            patch_basename="issue_515_v1.zip",
            raw_command="python3 scripts/am_patch.py 515",
            canonical_command=["python3", "scripts/am_patch.py", "515"],
            status="success",
        )
    )
    db.append_log_line(job_id, "alpha")
    db.append_event_line(job_id, '{"type":"status","event":"done"}')


def _backups_dir(repo_root: Path) -> Path:
    return repo_root / "patches" / "artifacts" / "backups"


@pytest.mark.asyncio
async def test_startup_backup_trigger_manual_creates_no_backup(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, trigger_policy="manual")
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "db_primary"
        assert core.backend_mode_state.last_recovery["backup_trigger_policy"] == "manual"
        assert core.backend_mode_state.last_recovery["startup_backup_created"] is False
        assert not _backups_dir(repo_root).exists()
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_startup_backup_trigger_always_writes_verified_backup(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, trigger_policy="startup_always")
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    await core.startup()
    try:
        recovery = core.backend_mode_state.last_recovery
        assert core.backend_mode_state.mode == "db_primary"
        assert recovery["backup_trigger_policy"] == "startup_always"
        assert recovery["startup_backup_created"] is True
        backup_path = Path(str(recovery["startup_backup_path"]))
        assert backup_path.is_file()
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_startup_backup_trigger_after_recovery_only_runs_after_restore(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, trigger_policy="startup_after_recovery")
    patches_root, db = _build_db(repo_root)
    _seed_terminal_job(db, job_id="job-515-trigger")
    first_backup = create_verified_backup(
        db_path=db.cfg.db_path,
        patches_root=patches_root,
        settings=WebJobsBackupSettings(
            enabled=True,
            destination_template="artifacts/backups/web_jobs_backup_{timestamp}.sqlite3",
            retain_count=10,
            verify_after_backup=True,
            trigger_policy="manual",
            restore_source_preference=("latest_backup",),
        ),
    )
    db.cfg.db_path.write_text("not-a-sqlite-db", encoding="utf-8")
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    await core.startup()
    try:
        recovery = core.backend_mode_state.last_recovery
        backups = sorted(_backups_dir(repo_root).glob("*.sqlite3"))
        assert core.backend_mode_state.mode == "db_primary"
        assert recovery["recovery_action"] == "restored_from_verified_backup"
        assert recovery["backup_trigger_policy"] == "startup_after_recovery"
        assert recovery["startup_backup_created"] is True
        assert len(backups) == 2
        assert Path(str(recovery["startup_backup_path"])) != first_backup.path
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_invalid_backup_trigger_policy_fails_startup(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, trigger_policy="broken_policy")
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    with pytest.raises(ValueError, match="invalid_web_jobs_backup_trigger_policy"):
        await core.startup()
