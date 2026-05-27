from __future__ import annotations

import contextlib
import json
import socket
import time
from pathlib import Path
from typing import cast


def _is_connected_event(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    payload = cast(dict[object, object], obj)
    return payload.get("type") == "control" and payload.get("event") == "connected"


def _is_result_event(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    payload = cast(dict[object, object], obj)
    return payload.get("type") == "result"


def _validate_result(obj: dict[str, object]) -> dict[str, object] | None:
    if "ok" not in obj or "return_code" not in obj:
        return None
    ok = obj.get("ok")
    rc = obj.get("return_code")
    if not isinstance(ok, bool):
        return None
    if not isinstance(rc, int):
        return None
    out: dict[str, object] = {"ok": ok, "return_code": rc}
    lp = obj.get("log_path")
    jp = obj.get("json_path")
    if isinstance(lp, str) and lp:
        out["log_path"] = lp
    if isinstance(jp, str) and jp:
        out["json_path"] = jp
    return out


def read_ipc_result(
    socket_path: Path,
    *,
    connect_timeout_s: float,
    total_timeout_s: float,
) -> dict[str, object] | None:
    """Read the runner IPC NDJSON stream until a type="result" event is observed.

    total_timeout_s <= 0 means no independent total timeout; the function then relies
    on peer closure or socket errors to stop.
    """

    connect_deadline = time.monotonic() + max(0.0, float(connect_timeout_s))
    total_deadline: float | None
    if float(total_timeout_s) > 0:
        total_deadline = time.monotonic() + float(total_timeout_s)
    else:
        total_deadline = None

    s: socket.socket | None = None
    while True:
        if time.monotonic() >= connect_deadline:
            return None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(str(socket_path))
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
            time.sleep(0.05)
            continue

    assert s is not None

    try:
        s.settimeout(0.2)
        fp = s.makefile("r", encoding="utf-8", newline="\n")
        connected = False
        result: dict[str, object] | None = None

        while True:
            if total_deadline is not None and time.monotonic() >= total_deadline:
                break
            try:
                line = fp.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            try:
                parsed: object = json.loads(line)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            obj = {
                str(key): value
                for key, value in cast(dict[object, object], parsed).items()
            }

            if not connected and _is_connected_event(obj):
                connected = True
                continue

            if connected and _is_result_event(obj):
                valid = _validate_result(obj)
                if valid is not None:
                    result = valid

        return result
    finally:
        with contextlib.suppress(Exception):
            s.close()
