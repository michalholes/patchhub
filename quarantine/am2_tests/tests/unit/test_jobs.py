from __future__ import annotations

from pathlib import Path

import pytest

from audiomason.core.jobs.api import JobService, _utcnow_iso
from audiomason.core.jobs.model import JobState, JobType
from audiomason.core.jobs.store import JobStore


@pytest.fixture()
def jobs_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Ensure Path.home() resolves under tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_job_store_roundtrip(jobs_home: Path) -> None:
    store = JobStore()
    service = JobService(store=store)

    job = service.create_job(JobType.PROCESS, meta={"source": "test"})
    loaded = service.get_job(job.job_id)

    assert loaded.job_id == job.job_id
    assert loaded.type == JobType.PROCESS
    assert loaded.state == JobState.PENDING
    assert loaded.meta["source"] == "test"

    # Layout exists
    root = jobs_home / ".audiomason" / "jobs" / job.job_id
    assert (root / "job.json").exists()
    assert (root / "job.log").exists()


def test_list_jobs_is_deterministic(jobs_home: Path) -> None:
    store = JobStore()
    service = JobService(store=store)

    j1 = service.create_job(JobType.PROCESS)
    j2 = service.create_job(JobType.DAEMON)
    jobs = service.list_jobs()

    assert [j.job_id for j in jobs] == sorted([j1.job_id, j2.job_id])


def test_state_transitions_forbidden(jobs_home: Path) -> None:
    service = JobService(store=JobStore())
    job = service.create_job(JobType.PROCESS)

    # Direct illegal transition: pending -> succeeded
    with pytest.raises(ValueError):
        job.transition(JobState.SUCCEEDED)


def test_cancel_pending_becomes_cancelled(jobs_home: Path) -> None:
    service = JobService(store=JobStore())
    job = service.create_job(JobType.PROCESS)

    cancelled = service.cancel_job(job.job_id)
    assert cancelled.state == JobState.CANCELLED
    assert cancelled.finished_at is not None

    # Log contains cancellation line
    text, _ = service.read_log(job.job_id, offset=0)
    assert "cancelled" in text


def test_cancel_running_sets_cancel_requested(jobs_home: Path) -> None:
    service = JobService(store=JobStore())
    job = service.create_job(JobType.PROCESS)

    # Simulate running state
    job.transition(JobState.RUNNING)
    job.started_at = _utcnow_iso()
    service.store.save_job(job)

    updated = service.cancel_job(job.job_id)
    assert updated.state == JobState.RUNNING
    assert updated.cancel_requested is True

    text, _ = service.read_log(job.job_id, offset=0)
    assert "cancel requested" in text
