from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import uuid
from pathlib import Path
from typing import Any

_PROTOCOL = "am_patch_ipc/1"


def job_socket_path(job_id: str) -> str:
    return str(Path("/tmp/audiomason") / f"patchhub_{job_id}.sock")


def _cancel_payload(cmd_id: str) -> bytes:
    req: dict[str, Any] = {
        "protocol": _PROTOCOL,
        "type": "cmd",
        "cmd_id": cmd_id,
        "cmd": "cancel",
        "args": {},
    }
    return (json.dumps(req, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


async def send_cancel_async(socket_path: str) -> bool:
    """Send cancel to runner IPC socket (async).

    This preserves the synchronous semantics: return True only if a matching
    reply is received with ok=true.
    """

    cmd_id = "patchhub_" + uuid.uuid4().hex
    payload = _cancel_payload(cmd_id)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except Exception:
        return False

    try:
        writer.write(payload)
        await writer.drain()

        while True:
            raw = await reader.readline()
            if not raw:
                return False
            try:
                line = raw.decode("utf-8")
            except Exception:
                line = raw.decode("utf-8", errors="replace")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("type", "")) != "reply":
                continue
            if str(obj.get("cmd_id", "")) != cmd_id:
                continue
            return bool(obj.get("ok") is True)
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def send_cancel_sync(socket_path: str) -> bool:
    """Send cancel to runner IPC socket (synchronous).

    Kept for the legacy sync backend.
    """

    cmd_id = "patchhub_" + uuid.uuid4().hex
    payload = _cancel_payload(cmd_id)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(socket_path)
        fp = s.makefile("rwb", buffering=0)
        try:
            fp.write(payload)
            while True:
                raw = fp.readline()
                if not raw:
                    return False
                try:
                    line = raw.decode("utf-8")
                except Exception:
                    line = raw.decode("utf-8", errors="replace")
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("type", "")) != "reply":
                    continue
                if str(obj.get("cmd_id", "")) != cmd_id:
                    continue
                return bool(obj.get("ok") is True)
        finally:
            with contextlib.suppress(Exception):
                fp.close()
            with contextlib.suppress(Exception):
                s.close()
    except Exception:
        return False
