from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from patchhub.web_jobs_db import WebJobsDatabase

_CHUNK_BYTES = 8192
_MAX_LINE_BYTES = 64 * 1024 * 1024
_PROTOCOL = "am_patch_ipc/1"
_READY_CMD_ID = "patchhub_ready"


def _oversize_notice(*, dropped_bytes: int) -> str:
    payload = {
        "type": "patchhub_notice",
        "code": "IPC_LINE_TOO_LARGE_DROPPED",
        "dropped_bytes": dropped_bytes,
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _write_line(
    *,
    f,
    line: str,
    publish: Callable[[str, int], None] | None,
    job_db: WebJobsDatabase | None,
    job_id: str,
) -> int:
    line = line.rstrip("\n")
    if not line.strip():
        return 0

    if job_db is not None and job_id:
        seq = job_db.append_event_line(job_id, line)
    else:
        f.write(line + "\n")
        seq = f.tell()
    if publish is not None:
        publish(line, seq)
    return seq


def _parse_line_obj(line: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _event_seq(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _command_payload(*, cmd_id: str, cmd: str, args: dict[str, Any]) -> bytes:
    req: dict[str, Any] = {
        "protocol": _PROTOCOL,
        "type": "cmd",
        "cmd_id": cmd_id,
        "cmd": cmd,
        "args": args,
    }
    return (json.dumps(req, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


async def _send_command(
    *,
    writer: asyncio.StreamWriter,
    cmd_id: str,
    cmd: str,
    args: dict[str, Any],
) -> None:
    writer.write(_command_payload(cmd_id=cmd_id, cmd=cmd, args=args))
    await writer.drain()


async def _connect_and_stream(
    socket_path: str,
    jsonl_path: Path | None,
    publish: Callable[[str, int], None] | None,
    *,
    job_db: WebJobsDatabase | None,
    job_id: str,
) -> None:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        f = jsonl_path.open("a", encoding="utf-8")
    else:
        f = None
    try:
        flush_every = 20
        n = 0
        buf = b""
        ready_sent = False
        drain_sent = False
        while True:
            chunk = await reader.read(_CHUNK_BYTES)
            if not chunk:
                if buf.strip():
                    line = buf.decode("utf-8", errors="replace")
                    _write_line(f=f, line=line, publish=publish, job_db=job_db, job_id=job_id)
                return

            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break

                line_bytes = buf[:nl]
                buf = buf[nl + 1 :]

                if not line_bytes.strip():
                    continue

                line = line_bytes.decode("utf-8", errors="replace")
                _write_line(f=f, line=line, publish=publish, job_db=job_db, job_id=job_id)
                n += 1
                obj = _parse_line_obj(line)

                if (
                    not ready_sent
                    and obj is not None
                    and str(obj.get("type", "")) == "control"
                    and str(obj.get("event", "")) == "connected"
                ):
                    try:
                        await _send_command(
                            writer=writer, cmd_id=_READY_CMD_ID, cmd="ready", args={}
                        )
                        ready_sent = True
                    except Exception:
                        pass

                if (
                    not drain_sent
                    and obj is not None
                    and str(obj.get("type", "")) == "control"
                    and str(obj.get("event", "")) == "eos"
                ):
                    seq = _event_seq(obj.get("seq"))
                    if seq is not None:
                        try:
                            if f is not None:
                                f.flush()
                            await _send_command(
                                writer=writer,
                                cmd_id=f"patchhub_drain_ack_{seq}",
                                cmd="drain_ack",
                                args={"seq": seq},
                            )
                            drain_sent = True
                        except Exception:
                            pass

                if n >= flush_every:
                    if f is not None:
                        f.flush()
                    n = 0

            if len(buf) > _MAX_LINE_BYTES:
                dropped = len(buf)
                buf = b""
                notice = _oversize_notice(dropped_bytes=dropped)
                _write_line(f=f, line=notice, publish=publish, job_db=job_db, job_id=job_id)
    finally:
        if f is not None:
            with contextlib.suppress(Exception):
                f.flush()
            with contextlib.suppress(Exception):
                f.close()
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def start_event_pump(
    *,
    socket_path: str,
    jsonl_path: Path | None = None,
    publish: Callable[[str, int], None] | None = None,
    job_db: WebJobsDatabase | None = None,
    job_id: str = "",
    connect_timeout_s: float = 10.0,
    retry_sleep_s: float = 0.25,
) -> None:
    deadline = asyncio.get_running_loop().time() + max(connect_timeout_s, 0.0)
    while True:
        try:
            await _connect_and_stream(
                socket_path,
                jsonl_path,
                publish,
                job_db=job_db,
                job_id=str(job_id),
            )
            return
        except FileNotFoundError:
            pass
        except ConnectionRefusedError:
            pass
        except OSError:
            pass

        if connect_timeout_s <= 0:
            return
        if asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(retry_sleep_s)
