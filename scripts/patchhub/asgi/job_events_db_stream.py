from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from patchhub.live_event_retention import LIVE_EVENT_RETENTION_MIN
from patchhub.web_jobs_db import WebJobsDatabase

from .job_event_broker import JobEventBroker


async def stream_job_events_db_live(
    *,
    job_id: str,
    db: WebJobsDatabase,
    in_memory_job: bool,
    job_status: Callable[[], Awaitable[str | None]],
    get_broker: Callable[[], Awaitable[JobEventBroker | None]],
    tail_lines: int = LIVE_EVENT_RETENTION_MIN,
    broker_poll_interval_s: float = 0.1,
    ping_interval_s: float = 10.0,
) -> AsyncIterator[bytes]:
    if not in_memory_job:
        async for chunk in stream_job_events_db_history(
            job_id=job_id,
            db=db,
            job_status=job_status,
            ping_interval_s=ping_interval_s,
        ):
            yield chunk
        return

    tail_rows, snapshot_seq = await asyncio.to_thread(db.read_event_tail, job_id, lines=tail_lines)
    for row in tail_rows:
        if row.raw_line.strip():
            yield f"data: {row.raw_line}\n\n".encode()

    last_ping = asyncio.get_running_loop().time()
    while True:
        broker = await get_broker()
        if broker is not None:
            break
        status = await job_status()
        if status is None:
            data = json.dumps({"reason": "job_not_found"}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return
        if status not in {"queued", "running"}:
            data = json.dumps({"reason": "job_completed", "status": str(status)}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return
        now = asyncio.get_running_loop().time()
        if now - last_ping >= ping_interval_s:
            yield b": ping\n\n"
            last_ping = now
        await asyncio.sleep(broker_poll_interval_s)

    sub = broker.subscribe(after_offset=snapshot_seq).__aiter__()
    while True:
        try:
            line = await asyncio.wait_for(sub.__anext__(), timeout=10.0)
        except TimeoutError:
            yield b": ping\n\n"
            continue
        except StopAsyncIteration:
            break
        yield f"data: {line}\n\n".encode()

    status = await job_status()
    data = json.dumps({"reason": "job_completed", "status": status or ""}, ensure_ascii=True)
    yield f"event: end\ndata: {data}\n\n".encode()


async def stream_job_events_db_history(
    *,
    job_id: str,
    db: WebJobsDatabase,
    job_status: Callable[[], Awaitable[str | None]],
    ping_interval_s: float = 10.0,
    poll_interval_s: float = 0.2,
) -> AsyncIterator[bytes]:
    last_seq = 0
    last_growth = asyncio.get_running_loop().time()
    last_ping = asyncio.get_running_loop().time()
    while True:
        status = await job_status()
        if status is None:
            data = json.dumps({"reason": "job_not_found"}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return
        rows = await asyncio.to_thread(db.read_event_rows, job_id, after_seq=last_seq, limit=2000)
        if rows:
            last_growth = asyncio.get_running_loop().time()
            for row in rows:
                if row.raw_line.strip():
                    yield f"data: {row.raw_line}\n\n".encode()
                last_seq = row.seq
        now = asyncio.get_running_loop().time()
        if now - last_ping >= ping_interval_s:
            yield b": ping\n\n"
            last_ping = now
        if status != "running" and now - last_growth >= 0.5:
            data = json.dumps({"reason": "job_completed", "status": str(status)}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return
        await asyncio.sleep(poll_interval_s)
