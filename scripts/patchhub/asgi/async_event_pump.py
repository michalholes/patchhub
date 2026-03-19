from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from patchhub.web_jobs_db import WebJobsDatabase

from .async_events_socket import CANCEL_REPLY_TIMEOUT_S

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


class EventPumpCommandChannel:
    def __init__(self) -> None:
        self._mu = asyncio.Lock()
        self._send_mu = asyncio.Lock()
        self._writer: asyncio.StreamWriter | None = None
        self._waiters: dict[str, asyncio.Future[bool]] = {}
        self._closed = False

    async def attach_writer(self, writer: asyncio.StreamWriter) -> None:
        async with self._mu:
            self._writer = writer
            self._closed = False

    async def close(self) -> None:
        async with self._mu:
            self._closed = True
            self._writer = None
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(False)

    def deliver_reply(self, obj: dict[str, Any] | None) -> bool:
        if obj is None:
            return False
        if str(obj.get("type", "")) != "reply":
            return False
        cmd_id = str(obj.get("cmd_id", ""))
        waiter = self._waiters.get(cmd_id)
        if waiter is None:
            return False
        if not waiter.done():
            waiter.set_result(bool(obj.get("ok") is True))
        return True

    async def send(
        self,
        *,
        cmd: str,
        args: dict[str, Any],
        cmd_id: str | None = None,
        cmd_id_prefix: str = "patchhub_cmd",
        timeout_s: float = CANCEL_REPLY_TIMEOUT_S,
    ) -> bool:
        actual_cmd_id = cmd_id or f"{cmd_id_prefix}_{uuid.uuid4().hex}"
        waiter = asyncio.get_running_loop().create_future()

        async with self._mu:
            writer = self._writer
            if self._closed or writer is None or writer.is_closing():
                return False
            self._waiters[actual_cmd_id] = waiter

        try:
            async with self._send_mu:
                writer.write(
                    _command_payload(
                        cmd_id=actual_cmd_id,
                        cmd=cmd,
                        args=args,
                    )
                )
                await writer.drain()
            return bool(await asyncio.wait_for(waiter, timeout=max(timeout_s, 0.0)))
        except Exception:
            return False
        finally:
            async with self._mu:
                self._waiters.pop(actual_cmd_id, None)


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


def _track_background_command(
    tasks: set[asyncio.Task[bool]],
    coro,
) -> None:
    task = asyncio.create_task(coro)
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _connect_and_stream(
    socket_path: str,
    jsonl_path: Path | None,
    publish: Callable[[str, int], None] | None,
    *,
    command_channel: EventPumpCommandChannel,
    job_db: WebJobsDatabase | None,
    job_id: str,
) -> None:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    await command_channel.attach_writer(writer)
    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        f = jsonl_path.open("a", encoding="utf-8")
    else:
        f = None
    background_commands: set[asyncio.Task[bool]] = set()
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
                    obj = _parse_line_obj(line)
                    if not command_channel.deliver_reply(obj):
                        _write_line(
                            f=f,
                            line=line,
                            publish=publish,
                            job_db=job_db,
                            job_id=job_id,
                        )
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
                obj = _parse_line_obj(line)
                if command_channel.deliver_reply(obj):
                    continue

                _write_line(f=f, line=line, publish=publish, job_db=job_db, job_id=job_id)
                n += 1

                if (
                    not ready_sent
                    and obj is not None
                    and str(obj.get("type", "")) == "control"
                    and str(obj.get("event", "")) == "connected"
                ):
                    _track_background_command(
                        background_commands,
                        command_channel.send(
                            cmd="ready",
                            args={},
                            cmd_id=_READY_CMD_ID,
                        ),
                    )
                    ready_sent = True

                if (
                    not drain_sent
                    and obj is not None
                    and str(obj.get("type", "")) == "control"
                    and str(obj.get("event", "")) == "eos"
                ):
                    seq = _event_seq(obj.get("seq"))
                    if seq is not None:
                        if f is not None:
                            f.flush()
                        _track_background_command(
                            background_commands,
                            command_channel.send(
                                cmd="drain_ack",
                                args={"seq": seq},
                                cmd_id=f"patchhub_drain_ack_{seq}",
                            ),
                        )
                        drain_sent = True

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
        for task in list(background_commands):
            if task.done():
                continue
            task.cancel()
        for task in list(background_commands):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await command_channel.close()
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
    command_channel: EventPumpCommandChannel | None = None,
    job_db: WebJobsDatabase | None = None,
    job_id: str = "",
    connect_timeout_s: float = 10.0,
    retry_sleep_s: float = 0.25,
) -> None:
    active_channel = command_channel or EventPumpCommandChannel()
    deadline = asyncio.get_running_loop().time() + max(connect_timeout_s, 0.0)
    while True:
        try:
            await _connect_and_stream(
                socket_path,
                jsonl_path,
                publish,
                command_channel=active_channel,
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
