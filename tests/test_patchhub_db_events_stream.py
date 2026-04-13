# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sqlite3
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
    seeded_db.append_event_lines(
        "job-514-events",
        [f'{{"type":"log","msg":"{idx}"}}' for idx in range(2, 20_006)],
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


def test_web_jobs_db_round_trip_preserves_commit_and_target_metadata(
    seeded_db: WebJobsDatabase,
) -> None:
    seeded_db.upsert_job(
        JobRecord(
            job_id="job-361-roundtrip",
            created_utc="2026-03-20T10:00:00Z",
            mode="patch",
            issue_id="361",
            commit_summary="Persisted round-trip",
            patch_basename="issue_361_v1.zip",
            raw_command="python3 scripts/am_patch.py 361",
            canonical_command=["python3", "scripts/am_patch.py", "361"],
            commit_message="Persisted commit",
            zip_target_repo="patchhub",
            selected_target_repo="audiomason2",
            effective_runner_target_repo="audiomason2",
            target_mismatch=True,
            run_start_sha="abc123",
            run_end_sha="def456",
            revert_source_job_id="job-360-source",
        )
    )

    payload = seeded_db.load_job_json("job-361-roundtrip")
    assert payload is not None
    assert payload["commit_message"] == "Persisted commit"
    assert payload["zip_target_repo"] == "patchhub"
    assert payload["selected_target_repo"] == "audiomason2"
    assert payload["effective_runner_target_repo"] == "audiomason2"
    assert payload["target_mismatch"] is True
    assert payload["run_start_sha"] == "abc123"
    assert payload["run_end_sha"] == "def456"
    assert payload["revert_source_job_id"] == "job-360-source"

    record = seeded_db.load_job_record("job-361-roundtrip")
    assert record is not None
    assert record.commit_message == "Persisted commit"
    assert record.zip_target_repo == "patchhub"
    assert record.selected_target_repo == "audiomason2"
    assert record.effective_runner_target_repo == "audiomason2"
    assert record.target_mismatch is True
    assert record.run_start_sha == "abc123"
    assert record.run_end_sha == "def456"
    assert record.revert_source_job_id == "job-360-source"


def test_web_jobs_db_additive_migration_keeps_existing_rows(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.db_path)
    conn.executescript(
        """
        CREATE TABLE web_jobs (
            job_id TEXT PRIMARY KEY,
            created_utc TEXT NOT NULL,
            created_unix_ms INTEGER NOT NULL,
            mode TEXT NOT NULL,
            issue_id_raw TEXT NOT NULL,
            issue_id_int INTEGER,
            commit_summary TEXT NOT NULL,
            patch_basename TEXT,
            raw_command TEXT NOT NULL,
            canonical_command_json TEXT NOT NULL,
            status TEXT NOT NULL,
            started_utc TEXT,
            ended_utc TEXT,
            return_code INTEGER,
            error TEXT,
            cancel_requested_utc TEXT,
            cancel_ack_utc TEXT,
            cancel_source TEXT,
            original_patch_path TEXT,
            effective_patch_path TEXT,
            effective_patch_kind TEXT,
            selected_patch_entries_json TEXT NOT NULL,
            selected_repo_paths_json TEXT NOT NULL,
            applied_files_json TEXT NOT NULL,
            applied_files_source TEXT NOT NULL,
            last_log_seq INTEGER NOT NULL DEFAULT 0,
            last_event_seq INTEGER NOT NULL DEFAULT 0,
            row_rev INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute(
        """
        INSERT INTO web_jobs(
            job_id, created_utc, created_unix_ms, mode, issue_id_raw, issue_id_int,
            commit_summary, patch_basename, raw_command, canonical_command_json, status,
            started_utc, ended_utc, return_code, error, cancel_requested_utc,
            cancel_ack_utc, cancel_source, original_patch_path, effective_patch_path,
            effective_patch_kind, selected_patch_entries_json, selected_repo_paths_json,
            applied_files_json, applied_files_source, last_log_seq, last_event_seq, row_rev
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            "job-legacy",
            "2026-03-20T10:00:00Z",
            0,
            "patch",
            "361",
            361,
            "Legacy summary",
            "issue_361_v1.zip",
            "python3 scripts/am_patch.py 361",
            '["python3","scripts/am_patch.py","361"]',
            "success",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "[]",
            "[]",
            "[]",
            "unavailable",
            0,
            0,
            1,
        ),
    )
    conn.commit()
    conn.close()

    db = WebJobsDatabase(cfg)
    payload = db.load_job_json("job-legacy")
    assert payload is not None
    assert payload["job_id"] == "job-legacy"
    assert payload["commit_message"] is None
    assert payload["zip_target_repo"] is None
    assert payload["selected_target_repo"] is None
    assert payload["effective_runner_target_repo"] is None
    assert payload["target_mismatch"] is False
    assert payload["run_start_sha"] is None
    assert payload["run_end_sha"] is None
    assert payload["revert_source_job_id"] is None

    with sqlite3.connect(cfg.db_path) as verify_conn:
        columns = {row[1] for row in verify_conn.execute("PRAGMA table_info(web_jobs)").fetchall()}
    assert {
        "commit_message",
        "zip_target_repo",
        "selected_target_repo",
        "effective_runner_target_repo",
        "target_mismatch",
        "run_start_sha",
        "run_end_sha",
        "revert_source_job_id",
    }.issubset(columns)
