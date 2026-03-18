# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config
from patchhub.models import JobRecord
from patchhub.web_jobs_backup_scheduler import maybe_create_interval_backup_once
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_recovery import read_runtime_state


def _write_backup_cfg(
    repo_root: Path,
    *,
    trigger_policy: str = "interval_hours",
    interval_hours: object = 4,
    check_interval_minutes: object = 5,
) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "[web_jobs_backup]",
                'destination_template = "artifacts/backups/web_jobs_backup_{timestamp}.sqlite3"',
                "retain_count = 10",
                "verify_after_write = true",
                f"trigger_policy = {json.dumps(trigger_policy)}",
                f"interval_hours = {json.dumps(interval_hours)}",
                f"check_interval_minutes = {json.dumps(check_interval_minutes)}",
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


def _seed_job(db: WebJobsDatabase, *, job_id: str) -> None:
    db.upsert_job(
        JobRecord(
            job_id=job_id,
            created_utc="2026-03-10T12:30:00Z",
            mode="patch",
            issue_id="518",
            commit_summary="interval backup",
            patch_basename="issue_518_v1.zip",
            raw_command="python3 scripts/am_patch.py 518",
            canonical_command=["python3", "scripts/am_patch.py", "518"],
            status="success",
        )
    )
    db.append_log_line(job_id, "alpha")
    db.append_event_line(job_id, '{"type":"status","event":"done"}')


def _write_runtime_state(patches_root: Path, *, hours_ago: int) -> None:
    path = patches_root / "artifacts" / "web_jobs_runtime_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(
        json.dumps(
            {
                "state": "clean",
                "last_verified_backup_utc": stamp,
                "last_verified_backup_path": "artifacts/backups/old.sqlite3",
                "last_verified_backup_status": "verified",
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_interval_backup_creates_backup_when_due(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, interval_hours=4, check_interval_minutes=1)
    patches_root, db = _build_db(repo_root)
    _seed_job(db, job_id="job-518-due")
    _write_runtime_state(patches_root, hours_ago=5)

    created = maybe_create_interval_backup_once(
        repo_root=repo_root,
        patches_root=patches_root,
        db_cfg=db.cfg,
        mode="db_primary",
    )

    assert created is not None
    assert created.is_file()
    state = read_runtime_state(patches_root)
    assert state["last_verified_backup_path"] == str(created)
    assert state["last_verified_backup_status"] == "verified"


def test_interval_backup_skips_when_not_due(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, interval_hours=4, check_interval_minutes=1)
    patches_root, db = _build_db(repo_root)
    _seed_job(db, job_id="job-518-not-due")
    _write_runtime_state(patches_root, hours_ago=1)

    created = maybe_create_interval_backup_once(
        repo_root=repo_root,
        patches_root=patches_root,
        db_cfg=db.cfg,
        mode="db_primary",
    )

    assert created is None


@pytest.mark.asyncio
async def test_interval_scheduler_stays_idle_in_file_emergency_mode(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(repo_root, interval_hours=1, check_interval_minutes=1)
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())
    core.backend_mode_state.activate_file_emergency({"selected_mode": "file_emergency"})

    await core.backup_scheduler.start()
    try:
        await asyncio.sleep(0)
        assert core.backup_scheduler._task is None
    finally:
        await core.backup_scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interval_hours", "check_interval_minutes", "expected_error"),
    [
        (0, 1, "invalid_web_jobs_backup_interval_hours:0"),
        (1, 0, "invalid_web_jobs_backup_check_interval_minutes:0"),
        ("oops", 1, "invalid_web_jobs_backup_interval_hours:oops"),
        (1, "oops", "invalid_web_jobs_backup_check_interval_minutes:oops"),
    ],
)
async def test_invalid_interval_backup_config_fails_startup(
    tmp_path: Path,
    interval_hours: object,
    check_interval_minutes: object,
    expected_error: str,
) -> None:
    repo_root = tmp_path / "repo"
    _write_backup_cfg(
        repo_root,
        interval_hours=interval_hours,
        check_interval_minutes=check_interval_minutes,
    )
    core = AsyncAppCore(repo_root=repo_root, cfg=_load_core_cfg())

    with pytest.raises(ValueError, match=re.escape(expected_error)):
        await core.startup()
