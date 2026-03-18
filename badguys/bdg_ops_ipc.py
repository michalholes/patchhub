from __future__ import annotations

import contextlib
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from badguys.bdg_evaluator import StepResult

_PROTOCOL = "am_patch_ipc/1"


@dataclass(frozen=True)
class QueuedIpcCommand:
    step_index: int
    cmd: str
    args: dict[str, Any]
    cmd_id: str
    delay_s: float
    connect_timeout_s: float
    reply_timeout_s: float
    wait_timeout_s: float
    wait_event_type: str | None
    wait_event_name: str | None
    event_arg_map: dict[str, str]


def runner_socket_name(*, argv: list[str], issue_id: str) -> str:
    prefix = "--ipc-socket-name-template="
    template = "am_patch_ipc_{issue}.sock"
    for arg in argv:
        if arg.startswith(prefix):
            value = arg[len(prefix) :].strip()
            if value:
                template = value
            break
    return template.replace("{issue}", issue_id)


def runner_socket_path(
    *,
    patches_dir: Path,
    issue_id: str,
    socket_name: str,
    test_mode: bool,
    runner_pid: int,
) -> Path:
    if not test_mode:
        return patches_dir / socket_name
    return patches_dir / "_test_mode" / f"issue_{issue_id}_pid_{runner_pid}" / socket_name


def execute_ipc_send_command(
    *,
    step_runner_cfg: dict[str, object],
    params: dict[str, object],
    test_id: str,
    step_index: int,
) -> StepResult:
    cmd = params.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        raise SystemExit("FAIL: bdg: IPC_SEND_COMMAND requires non-empty cmd")
    raw_args = params.get("args", {})
    if not isinstance(raw_args, dict):
        raise SystemExit("FAIL: bdg: IPC_SEND_COMMAND args must be object")
    raw_cmd_id = params.get("cmd_id")
    if raw_cmd_id is None:
        cmd_id = f"{test_id}_step_{int(step_index)}_{cmd.strip()}"
    elif isinstance(raw_cmd_id, str) and raw_cmd_id.strip():
        cmd_id = raw_cmd_id.strip()
    else:
        raise SystemExit("FAIL: bdg: IPC_SEND_COMMAND cmd_id must be non-empty string")

    plan = QueuedIpcCommand(
        step_index=int(step_index),
        cmd=cmd.strip(),
        args=dict(raw_args),
        cmd_id=cmd_id,
        delay_s=_as_timeout(params.get("delay_s", 0), label="delay_s"),
        connect_timeout_s=_as_timeout(
            params.get("connect_timeout_s", 3),
            label="connect_timeout_s",
        ),
        reply_timeout_s=_as_timeout(
            params.get("reply_timeout_s", 3),
            label="reply_timeout_s",
        ),
        wait_timeout_s=_as_timeout(
            params.get("wait_timeout_s", 10),
            label="wait_timeout_s",
        ),
        wait_event_type=_as_optional_str(params.get("wait_event_type"), label="wait_event_type"),
        wait_event_name=_as_optional_str(params.get("wait_event_name"), label="wait_event_name"),
        event_arg_map=_as_arg_map(params.get("event_arg_map", {})),
    )
    plans_obj = step_runner_cfg.setdefault("ipc_plans", [])
    if not isinstance(plans_obj, list):
        raise SystemExit("FAIL: bdg: ipc_plans must be list")
    plans_obj.append(plan)
    return StepResult(
        rc=0,
        stdout=None,
        stderr=None,
        value=f"queued:ipc_reply.step{int(step_index)}.json",
    )


def pop_ipc_plans(step_runner_cfg: dict[str, object]) -> list[QueuedIpcCommand]:
    raw = step_runner_cfg.pop("ipc_plans", [])
    if not isinstance(raw, list):
        raise SystemExit("FAIL: bdg: ipc_plans must be list")
    out: list[QueuedIpcCommand] = []
    for item in raw:
        if not isinstance(item, QueuedIpcCommand):
            raise SystemExit("FAIL: bdg: ipc_plans entry must be QueuedIpcCommand")
        out.append(item)
    return out


def has_pending_ipc_plans(step_runner_cfg: dict[str, object]) -> bool:
    raw = step_runner_cfg.get("ipc_plans", [])
    return isinstance(raw, list) and bool(raw)


def send_ipc_command(
    *,
    socket_path: Path,
    cmd: str,
    args: dict[str, Any],
    cmd_id: str,
    connect_timeout_s: float,
    reply_timeout_s: float,
) -> dict[str, Any]:
    req = {
        "protocol": _PROTOCOL,
        "type": "cmd",
        "cmd": cmd,
        "cmd_id": cmd_id,
        "args": dict(args),
    }
    deadline = time.monotonic() + max(0.0, float(connect_timeout_s))
    sock: socket.socket | None = None
    while True:
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "error": {
                    "code": "CONNECT_TIMEOUT",
                    "message": "ipc connect timeout",
                },
            }
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            sock.connect(str(socket_path))
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            if sock is not None:
                with contextlib.suppress(Exception):
                    sock.close()
            sock = None
            time.sleep(0.02)

    if sock is None:
        return {
            "ok": False,
            "error": {
                "code": "CONNECT_TIMEOUT",
                "message": "ipc connect timeout",
            },
        }

    try:
        fp = sock.makefile("rwb", buffering=0)
        fp.write(_json_line(req))
        deadline = time.monotonic() + max(0.0, float(reply_timeout_s))
        while True:
            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "error": {
                        "code": "REPLY_TIMEOUT",
                        "message": "ipc reply timeout",
                    },
                }
            try:
                line = fp.readline()
            except TimeoutError:
                continue
            except Exception:
                return {
                    "ok": False,
                    "error": {
                        "code": "REPLY_READ_ERROR",
                        "message": "ipc reply read failed",
                    },
                }
            if not line:
                return {
                    "ok": False,
                    "error": {
                        "code": "EOF",
                        "message": "ipc connection closed before reply",
                    },
                }
            try:
                obj = json.loads(line.decode("utf-8", errors="strict"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") != "reply":
                continue
            if str(obj.get("cmd_id", "")) != cmd_id:
                continue
            return obj
    finally:
        with contextlib.suppress(Exception):
            sock.close()


def _as_timeout(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"FAIL: bdg: IPC_SEND_COMMAND {label} must be number")
    out = float(value)
    if out < 0:
        raise SystemExit(f"FAIL: bdg: IPC_SEND_COMMAND {label} must be >= 0")
    return out


def _as_optional_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SystemExit(f"FAIL: bdg: IPC_SEND_COMMAND {label} must be string")
    text = value.strip()
    return text or None


def _as_arg_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SystemExit("FAIL: bdg: IPC_SEND_COMMAND event_arg_map must be object")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise SystemExit("FAIL: bdg: IPC_SEND_COMMAND event_arg_map must be dict[str, str]")
        out[key] = item
    return out


def _json_line(obj: dict[str, Any]) -> bytes:
    txt = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return (txt + "\n").encode("utf-8")


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
