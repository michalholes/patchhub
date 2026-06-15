# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import pytest

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_retention_scheduler import WebJobsRetentionJanitor


def _copy_cfg(repo_root: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    target = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _rewrite_retention_block(repo_root: Path, *, block: list[str]) -> None:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    lines = cfg_path.read_text(encoding="utf-8").splitlines()
    start = lines.index("[web_jobs_retention]")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("["):
            end = index
            break
    new_lines = lines[:start] + ["[web_jobs_retention]", *block] + lines[end:]
    cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _build_db(tmp_path: Path) -> tuple[Path, WebJobsDatabase]:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    _copy_cfg(repo_root)
    return repo_root, WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))


def _seed_terminal_job(
    db: WebJobsDatabase,
    *,
    job_id: str,
    created_utc: str,
) -> None:
    job = JobRecord(
        job_id=job_id,
        created_utc=created_utc,
        mode="patch",
        issue_id="516",
        commit_summary=job_id,
        patch_basename="issue_516.zip",
        raw_command="python3 scripts/am_patch.py 516",
        canonical_command=["python3", "scripts/am_patch.py", "516"],
        status="running",
    )
    db.upsert_job(job)
    db.append_log_line(job_id, "line-1")
    db.append_log_line(job_id, "line-2")
    db.append_event_line(job_id, '{"type":"status","event":"done"}')
    job.status = "success"
    job.ended_utc = created_utc
    db.upsert_job(job)


class _BlockingJanitorDb:
    def __init__(self) -> None:
        self.calls = 0
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()
        self.started = threading.Event()
        self.release = threading.Event()

    def run_retention_janitor(self) -> bool:
        with self._lock:
            self.calls += 1
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.started.set()
        self.release.wait(1)
        with self._lock:
            self._active -= 1
        return True


def test_retention_janitor_prunes_old_terminal_jobs_and_keeps_stats(
    tmp_path: Path,
) -> None:
    repo_root, db = _build_db(tmp_path)
    _rewrite_retention_block(
        repo_root,
        block=[
            "jobs_keep_days = 3650",
            "logs_keep_days = 3650",
            "events_keep_days = 3650",
            "compact_after_jobs = 1000000",
            "compact_after_log_lines = 1000000",
            "compact_after_event_lines = 1000000",
            "max_completed_job_raw_log_lines = 1000000",
            "max_completed_job_raw_event_lines = 1000000",
            "max_completed_job_raw_age_days = 3650",
            "keep_recent_terminal_jobs_per_mode = 100",
            "compact_tail_lines = 20000",
            'reclaim_trigger_policy = "manual"',
            "reclaim_interval_seconds = 0",
            "reclaim_min_pruned_rows = 1",
        ],
    )
    _seed_terminal_job(
        db,
        job_id="job-516-old",
        created_utc="2026-03-01T10:00:00Z",
    )
    _seed_terminal_job(
        db,
        job_id="job-516-recent",
        created_utc="2026-04-01T10:00:00Z",
    )

    _rewrite_retention_block(
        repo_root,
        block=[
            "jobs_keep_days = 1",
            "logs_keep_days = 1",
            "events_keep_days = 1",
            "compact_after_jobs = 0",
            "compact_after_log_lines = 0",
            "compact_after_event_lines = 0",
            "max_completed_job_raw_log_lines = 1",
            "max_completed_job_raw_event_lines = 1",
            "max_completed_job_raw_age_days = 1",
            "keep_recent_terminal_jobs_per_mode = 1",
            "compact_tail_lines = 20000",
            'reclaim_trigger_policy = "manual"',
            "reclaim_interval_seconds = 0",
            "reclaim_min_pruned_rows = 1",
        ],
    )

    changed = db.run_retention_janitor()

    assert changed is True
    assert db.load_job_record("job-516-old") is None
    assert db.load_job_record("job-516-recent") is not None
    assert db.load_job_stats_summary()["jobs_total"] == 2


@pytest.mark.asyncio
async def test_retention_janitor_starts_and_runs_once_in_db_primary_mode() -> None:
    fake_db = _BlockingJanitorDb()
    janitor = WebJobsRetentionJanitor(db=fake_db, get_mode=lambda: "db_primary")

    await janitor.start()
    try:
        await asyncio.to_thread(fake_db.started.wait)
        assert fake_db.calls == 1
    finally:
        fake_db.release.set()
        await janitor.stop()

    assert fake_db.calls == 1


@pytest.mark.asyncio
async def test_retention_janitor_does_not_start_in_file_emergency_mode() -> None:
    fake_db = _BlockingJanitorDb()
    janitor = WebJobsRetentionJanitor(db=fake_db, get_mode=lambda: "file_emergency")

    await janitor.start()
    try:
        await asyncio.sleep(0)
        assert janitor._task is None
        assert fake_db.calls == 0
    finally:
        await janitor.stop()


@pytest.mark.asyncio
async def test_retention_janitor_serializes_tick_calls() -> None:
    fake_db = _BlockingJanitorDb()
    janitor = WebJobsRetentionJanitor(db=fake_db, get_mode=lambda: "db_primary")

    first = asyncio.create_task(janitor._tick_once())
    try:
        await asyncio.to_thread(fake_db.started.wait)
        second = asyncio.create_task(janitor._tick_once())
        await asyncio.sleep(0)
        assert fake_db.calls == 1
        assert fake_db.max_active == 1
        fake_db.release.set()
        await asyncio.gather(first, second)
    finally:
        fake_db.release.set()

    assert fake_db.calls == 2
    assert fake_db.max_active == 1
