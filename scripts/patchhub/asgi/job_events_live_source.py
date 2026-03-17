from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from patchhub.live_event_retention import (
    LIVE_EVENT_RETENTION_MIN,
    clamp_live_event_retention,
)

from .job_event_broker import JobEventBroker


def _read_tail_snapshot(
    path: Path,
    lines: int,
    *,
    max_bytes: int = 8_388_608,
) -> tuple[str, int]:
    if not path.exists():
        return "", 0

    lines = clamp_live_event_retention(lines)
    max_bytes = max(0, int(max_bytes))
    file_size = path.stat().st_size
    if file_size <= 0:
        return "", 0

    start = max(0, file_size - max_bytes)
    with path.open("rb") as f:
        f.seek(start)
        raw = f.read(file_size - start)

    if not raw:
        return "", file_size

    text = raw.decode("utf-8", errors="replace")
    parts = text.splitlines()
    return "\n".join(parts[-lines:]), file_size


async def stream_job_events_live_source(
    *,
    job_id: str,
    jsonl_path: Path,
    in_memory_job: bool,
    job_status: Callable[[], Awaitable[str | None]],
    get_broker: Callable[[], Awaitable[JobEventBroker | None]],
    historical_stream: Callable[[], AsyncIterator[bytes]],
    tail_lines: int = LIVE_EVENT_RETENTION_MIN,
    ping_interval_s: float = 10.0,
    broker_poll_interval_s: float = 0.1,
) -> AsyncIterator[bytes]:
    del job_id
    if not in_memory_job:
        async for chunk in historical_stream():
            yield chunk
        return

    tail, snapshot_end_offset = await asyncio.to_thread(
        _read_tail_snapshot,
        jsonl_path,
        tail_lines,
    )
    if tail:
        for line in tail.splitlines():
            if not line.strip():
                continue
            yield f"data: {line}\n\n".encode()

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

        if status not in ("queued", "running"):
            data = json.dumps(
                {"reason": "job_completed", "status": str(status)},
                ensure_ascii=True,
            )
            yield f"event: end\ndata: {data}\n\n".encode()
            return

        now = asyncio.get_running_loop().time()
        if now - last_ping >= ping_interval_s:
            yield b": ping\n\n"
            last_ping = now

        await asyncio.sleep(broker_poll_interval_s)

    sub = broker.subscribe(after_offset=snapshot_end_offset).__aiter__()
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
    data = json.dumps(
        {"reason": "job_completed", "status": status or ""},
        ensure_ascii=True,
    )
    yield f"event: end\ndata: {data}\n\n".encode()
