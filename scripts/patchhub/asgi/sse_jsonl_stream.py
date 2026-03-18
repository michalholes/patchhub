from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path


def _read_chunk_sync(path: Path, offset: int) -> tuple[bytes, int]:
    with path.open("rb") as fp:
        fp.seek(offset)
        chunk = fp.read()
        return chunk, fp.tell()


def _path_exists_sync(path: Path) -> bool:
    return path.exists()


async def stream_job_events_sse(
    *,
    job_id: str,
    jsonl_path: Path,
    job_status: Callable[[], Awaitable[str | None]],
    ping_interval_s: float = 10.0,
    poll_interval_s: float = 0.2,
) -> AsyncIterator[bytes]:
    offset = 0
    last_growth = asyncio.get_running_loop().time()
    last_ping = asyncio.get_running_loop().time()

    while True:
        status = await job_status()
        if status is None:
            data = json.dumps({"reason": "job_not_found"}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return

        exists = await asyncio.to_thread(_path_exists_sync, jsonl_path)
        if status == "running" and not exists:
            now = asyncio.get_running_loop().time()
            if now - last_ping >= ping_interval_s:
                yield b": ping\n\n"
                last_ping = now
            await asyncio.sleep(poll_interval_s)
            continue

        if not exists:
            data = json.dumps({"reason": "job_completed", "status": str(status)}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return

        try:
            chunk, end_pos = await asyncio.to_thread(_read_chunk_sync, jsonl_path, offset)
        except FileNotFoundError:
            data = json.dumps({"reason": "job_completed", "status": str(status)}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return
        except OSError:
            data = json.dumps({"reason": "io_error"}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return

        if chunk:
            last_growth = asyncio.get_running_loop().time()
            parts = chunk.split(b"\n")
            if chunk.endswith(b"\n"):
                complete = parts[:-1]
                tail = b""
            else:
                complete = parts[:-1]
                tail = parts[-1]
            for raw in complete:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    s = raw.decode("utf-8")
                except Exception:
                    s = raw.decode("utf-8", errors="replace")
                yield f"data: {s}\n\n".encode()
            offset = end_pos - len(tail)

        now = asyncio.get_running_loop().time()
        if now - last_ping >= ping_interval_s:
            yield b": ping\n\n"
            last_ping = now

        if status != "running" and now - last_growth >= 0.5:
            data = json.dumps({"reason": "job_completed", "status": str(status)}, ensure_ascii=True)
            yield f"event: end\ndata: {data}\n\n".encode()
            return

        await asyncio.sleep(poll_interval_s)
