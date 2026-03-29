# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.config import load_config
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


def _load_cfg() -> object:
    cfg_path = Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    return load_config(cfg_path)


def _running_job(job_id: str, *, mode: str = "patch") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        created_utc="2026-03-24T10:00:00Z",
        mode=mode,
        issue_id="379",
        commit_summary="Patch success cleanup",
        patch_basename="issue_379_v1.zip",
        raw_command="python3 scripts/am_patch.py 379",
        canonical_command=["python3", "scripts/am_patch.py", "379"],
        status="running",
    )


def _seed_db(repo_root: Path, *, job_id: str) -> None:
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id=job_id,
            created_utc="2026-03-24T09:00:00Z",
            mode="patch",
            issue_id="379",
            commit_summary="startup seed",
            patch_basename="issue_379_v1.zip",
            raw_command="python3 scripts/am_patch.py 379",
            canonical_command=["python3", "scripts/am_patch.py", "379"],
            status="success",
        )
    )


@pytest.mark.asyncio
async def test_create_app_startup_preserves_cleanup_callback_for_db_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def _fake_cleanup(core: object, job: JobRecord) -> None:
        calls.append((str(core.backend_mode_state.mode), job.job_id, job.status))

    monkeypatch.setattr("patchhub.asgi.asgi_app.run_patch_job_success_cleanup", _fake_cleanup)

    app = create_app(repo_root=tmp_path / "repo", cfg=_load_cfg())
    core = app.state.core
    initial_queue = core.queue
    initial_callback = initial_queue._on_patch_success

    assert initial_callback is not None

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "db_primary"
        assert core.queue is not initial_queue
        assert core.queue._on_patch_success is initial_callback

        job = _running_job("job-379-db-success")
        core.queue._jobs[job.job_id] = job

        changed = await core.queue._finalize_running_job(
            job.job_id,
            return_code=0,
            error=None,
        )

        assert changed is True
        assert calls == [("db_primary", "job-379-db-success", "success")]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_create_app_startup_runs_cleanup_for_failed_and_repair_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_cleanup(core: object, job: JobRecord) -> None:
        del core
        calls.append(job.job_id)

    monkeypatch.setattr("patchhub.asgi.asgi_app.run_patch_job_success_cleanup", _fake_cleanup)

    app = create_app(repo_root=tmp_path / "repo", cfg=_load_cfg())
    core = app.state.core

    await core.startup()
    try:
        fail_job = _running_job("job-379-fail")
        repair_job = _running_job("job-379-repair", mode="repair")
        core.queue._jobs[fail_job.job_id] = fail_job
        core.queue._jobs[repair_job.job_id] = repair_job

        await core.queue._finalize_running_job(
            fail_job.job_id,
            return_code=1,
            error="boom",
        )
        await core.queue._finalize_running_job(
            repair_job.job_id,
            return_code=0,
            error=None,
        )

        assert core.queue._jobs[fail_job.job_id].status == "fail"
        assert core.queue._jobs[repair_job.job_id].status == "success"
        assert calls == ["job-379-fail", "job-379-repair"]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_create_app_startup_runs_cleanup_for_queued_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_cleanup(core: object, job: JobRecord) -> None:
        del core
        calls.append((job.job_id, job.status))

    monkeypatch.setattr("patchhub.asgi.asgi_app.run_patch_job_success_cleanup", _fake_cleanup)

    app = create_app(repo_root=tmp_path / "repo", cfg=_load_cfg())
    core = app.state.core

    await core.startup()
    try:
        queued_job = JobRecord(
            job_id="job-379-queued-cancel",
            created_utc="2026-03-24T10:00:00Z",
            mode="patch",
            issue_id="379",
            commit_summary="Queued cancel",
            patch_basename="issue_379_v1.zip",
            raw_command="python3 scripts/am_patch.py 379",
            canonical_command=["python3", "scripts/am_patch.py", "379"],
            status="queued",
        )
        core.queue._jobs[queued_job.job_id] = queued_job

        changed = await core.queue._cancel_local(queued_job.job_id)

        assert changed is True
        assert core.queue._jobs[queued_job.job_id].status == "canceled"
        assert calls == [("job-379-queued-cancel", "canceled")]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_create_app_startup_preserves_cleanup_callback_for_file_emergency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def _fake_cleanup(core: object, job: JobRecord) -> None:
        calls.append((str(core.backend_mode_state.mode), job.job_id, job.status))

    monkeypatch.setattr("patchhub.asgi.asgi_app.run_patch_job_success_cleanup", _fake_cleanup)

    repo_root = tmp_path / "repo"
    _seed_db(repo_root, job_id="job-379-seed")

    def _force_invalid(path: Path) -> tuple[bool, str]:
        del path
        return False, "forced_invalid"

    monkeypatch.setattr("patchhub.web_jobs_recovery._validate_db_path", _force_invalid)

    app = create_app(repo_root=repo_root, cfg=_load_cfg())
    core = app.state.core
    initial_queue = core.queue
    initial_callback = initial_queue._on_patch_success

    assert initial_callback is not None

    await core.startup()
    try:
        assert core.backend_mode_state.mode == "file_emergency"
        assert core.queue is not initial_queue
        assert core.queue._on_patch_success is initial_callback

        job = _running_job("job-379-file-success")
        core.queue._jobs[job.job_id] = job

        changed = await core.queue._finalize_running_job(
            job.job_id,
            return_code=0,
            error=None,
        )

        assert changed is True
        assert calls == [("file_emergency", "job-379-file-success", "success")]
    finally:
        await core.shutdown()
