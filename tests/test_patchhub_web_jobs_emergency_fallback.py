# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_jobs import api_jobs_enqueue
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


class _DummyQueue:
    def enqueue(self, job: object) -> None:
        del job


class _LegacySelf:
    def __init__(self, core: AsyncAppCore) -> None:
        self.cfg = core.cfg
        self.jail = core.jail
        self.patches_root = core.patches_root
        self.jobs_root = core.jobs_root
        self.queue = _DummyQueue()
        self.queue_block_reason = core.queue_block_reason


def _seed_db(repo_root: Path) -> tuple[Path, WebJobsDatabase]:
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id="job-515-fallback",
            created_utc="2026-03-10T11:00:00Z",
            mode="patch",
            issue_id="515",
            commit_summary="Fallback seed",
            patch_basename="issue_515_v1.zip",
            raw_command="python3 scripts/am_patch.py 515",
            canonical_command=["python3", "scripts/am_patch.py", "515"],
            status="canceled",
            ended_utc="2026-03-10T11:01:00Z",
        )
    )
    db.append_log_line("job-515-fallback", "runner line")
    db.append_event_line("job-515-fallback", '{"type":"status","event":"canceled"}')
    return patches_root, db


def test_enqueue_is_blocked_until_backend_mode_is_resolved(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    core = AsyncAppCore(repo_root=repo_root, cfg=cfg)
    status, raw = api_jobs_enqueue(
        _LegacySelf(core),
        {
            "mode": "patch",
            "issue_id": "515",
            "commit_message": "msg",
            "patch_path": "x.zip",
        },
    )
    payload = json.loads(raw.decode("utf-8"))
    assert status == 409
    assert payload["error"] == "Backend mode selection is not finished"


@pytest.mark.asyncio
async def test_async_core_enters_file_emergency_mode_after_failed_db_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    patches_root, db = _seed_db(repo_root)
    marker_path = patches_root / "artifacts" / "web_jobs_runtime_state.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text('{"state":"dirty","session_id":"prev"}\n', encoding="utf-8")

    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    core = AsyncAppCore(repo_root=repo_root, cfg=cfg)

    def _force_invalid(path: Path) -> tuple[bool, str]:
        del path
        return False, "forced_invalid"

    monkeypatch.setattr("patchhub.web_jobs_recovery._validate_db_path", _force_invalid)

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "file_emergency"
        assert core.web_jobs_db is None
        assert core.queue_block_reason() is None
        job_json = json.loads((core.jobs_root / "job-515-fallback" / "job.json").read_text())
        assert job_json["job_id"] == "job-515-fallback"
        assert (core.jobs_root / "job-515-fallback" / "runner.log").read_text() == "runner line"
        assert core.indexer.ready() is True
    finally:
        await core.shutdown()
