# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.job_event_broker import JobEventBroker
from patchhub.asgi.job_events_db_stream import (
    stream_job_events_db_history,
    stream_job_events_db_live,
)
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


@pytest.fixture
def seeded_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    db = WebJobsDatabase(cfg)
    db.upsert_job(
        JobRecord(
            job_id="job-514-events",
            created_utc="2026-03-09T10:00:00Z",
            mode="patch",
            issue_id="514",
            commit_summary="DB primary",
            patch_basename="issue_514.zip",
            raw_command="python3 scripts/am_patch.py 514",
            canonical_command=["python3", "scripts/am_patch.py", "514"],
            status="success",
        )
    )
    db.append_event_line("job-514-events", '{"type":"log","msg":"queued"}')
    db.append_event_line("job-514-events", '{"type":"status","event":"done"}')
    return db


def test_upsert_job_preserves_db_history_counters(seeded_db: WebJobsDatabase) -> None:
    job = seeded_db.load_job_record("job-514-events")
    assert job is not None

    stale = JobRecord(
        job_id=job.job_id,
        created_utc=job.created_utc,
        mode=job.mode,
        issue_id=job.issue_id,
        commit_summary=job.commit_summary,
        patch_basename=job.patch_basename,
        raw_command=job.raw_command,
        canonical_command=list(job.canonical_command),
        status="running",
    )
    seeded_db.upsert_job(stale)

    payload = seeded_db.load_job_json("job-514-events")
    assert payload is not None
    assert payload["last_event_seq"] == 2
    assert payload["last_log_seq"] == 0

    next_event_seq = seeded_db.append_event_line(
        "job-514-events",
        '{"type":"log","msg":"after_status_upsert"}',
    )
    next_log_seq = seeded_db.append_log_line("job-514-events", "after status upsert")

    assert next_event_seq == 3
    assert next_log_seq == 1


@pytest.mark.asyncio
async def test_db_history_stream_replays_raw_ndjson_and_end_event(
    seeded_db: WebJobsDatabase,
) -> None:
    chunks: list[bytes] = []
    async for chunk in stream_job_events_db_history(
        job_id="job-514-events",
        db=seeded_db,
        job_status=lambda: asyncio.sleep(0, result="success"),
        poll_interval_s=0.01,
    ):
        chunks.append(chunk)

    text = b"".join(chunks).decode("utf-8")
    assert 'data: {"type":"log","msg":"queued"}' in text
    assert 'data: {"type":"status","event":"done"}' in text
    assert 'event: end\ndata: {"reason": "job_completed", "status": "success"}' in text


@pytest.mark.asyncio
async def test_db_live_stream_replays_db_tail_then_switches_to_broker(
    seeded_db: WebJobsDatabase,
) -> None:
    broker = JobEventBroker()

    async def _job_status() -> str | None:
        return "running"

    async def _get_broker() -> JobEventBroker | None:
        return broker

    stream = stream_job_events_db_live(
        job_id="job-514-events",
        db=seeded_db,
        in_memory_job=True,
        job_status=_job_status,
        get_broker=_get_broker,
        tail_lines=1,
        broker_poll_interval_s=0.01,
    )
    iterator = stream.__aiter__()

    first = (await iterator.__anext__()).decode("utf-8")
    assert first == 'data: {"type":"status","event":"done"}\n\n'

    broker.publish('{"type":"log","msg":"live"}', 3)
    second = (await iterator.__anext__()).decode("utf-8")
    assert second == 'data: {"type":"log","msg":"live"}\n\n'

    broker.close()
    third = (await iterator.__anext__()).decode("utf-8")
    assert third == 'event: end\ndata: {"reason": "job_completed", "status": "running"}\n\n'


@pytest.mark.asyncio
async def test_db_live_stream_default_tail_replays_20000_rows(
    seeded_db: WebJobsDatabase,
) -> None:
    for idx in range(2, 20_006):
        seeded_db.append_event_line(
            "job-514-events",
            f'{{"type":"log","msg":"{idx}"}}',
        )

    broker = JobEventBroker()
    broker.close()

    async def _job_status() -> str | None:
        return "success"

    async def _get_broker() -> JobEventBroker | None:
        return broker

    chunks = [
        chunk
        async for chunk in stream_job_events_db_live(
            job_id="job-514-events",
            db=seeded_db,
            in_memory_job=True,
            job_status=_job_status,
            get_broker=_get_broker,
        )
    ]

    data_lines = [chunk.decode("utf-8").strip() for chunk in chunks if chunk.startswith(b"data: ")]
    assert len(data_lines) == 20_000
    assert data_lines[0] == 'data: {"type":"log","msg":"6"}'
    assert data_lines[-1] == 'data: {"type":"log","msg":"20005"}'
