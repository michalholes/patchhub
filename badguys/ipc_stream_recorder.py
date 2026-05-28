from __future__ import annotations

import contextlib
import json
import shutil
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

JsonMap = dict[str, object]


@dataclass
class PreparedCommandPlan:
    protocol: str
    cmd: str
    cmd_id: str
    args: dict[str, object]
    delay_s: float
    wait_event_type: str | None
    wait_event_name: str | None
    event_arg_map: dict[str, str]
    request_path: Path
    reply_path: Path
    matched_event: JsonMap | None = None
    sent: bool = False
    done: bool = False


def _to_json_map(value: object) -> JsonMap | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in cast(dict[object, object], value).items()}


def _wait_socket_readable(sock: socket.socket, timeout_s: float | None) -> bool:
    deadline: float | None = (
        None if timeout_s is None else time.monotonic() + max(0.0, float(timeout_s))
    )

    while True:
        try:
            sock.recv(1, socket.MSG_PEEK)
            return True
        except BlockingIOError:
            pass
        except InterruptedError:
            continue
        except OSError:
            raise

        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(0.005)


def _copy_result_artifact(
    result: JsonMap,
    *,
    result_json_copy_path: Path | None,
    runner_jsonl_copy_path: Path | None,
    runner_log_copy_path: Path | None,
) -> str | None:
    if result_json_copy_path is not None:
        try:
            _write_json(result_json_copy_path, result)
        except OSError as exc:
            return f"write runner result failed: {result_json_copy_path}: {exc}"

    json_path = result.get("json_path")
    if runner_jsonl_copy_path is not None and isinstance(json_path, str) and json_path:
        err = _copy_result_artifact_path(
            src_path=json_path,
            dst_path=runner_jsonl_copy_path,
            label="json_path",
        )
        if err is not None:
            return err

    log_path = result.get("log_path")
    if runner_log_copy_path is not None and isinstance(log_path, str) and log_path:
        err = _copy_result_artifact_path(
            src_path=log_path,
            dst_path=runner_log_copy_path,
            label="log_path",
        )
        if err is not None:
            return err
    return None


def _remove_partial_artifact(dst_path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        dst_path.unlink()


def _copy_result_artifact_path(
    *,
    src_path: str,
    dst_path: Path,
    label: str,
) -> str | None:
    src = Path(src_path)
    if not src.exists():
        return f"missing runner {label}: {src}"
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst_path)
    except FileNotFoundError:
        _remove_partial_artifact(dst_path)
        return f"missing runner {label}: {src}"
    except OSError as exc:
        _remove_partial_artifact(dst_path)
        return f"copy runner {label} failed: {src} -> {dst_path}: {exc}"
    return None


def _result_artifact_copy_status(*, error: str | None) -> JsonMap:
    return {"ok": error is None, "error": error}


def _validate_result(obj: object) -> JsonMap | None:
    payload = _to_json_map(obj)
    if payload is None:
        return None
    if "ok" not in payload or "return_code" not in payload:
        return None
    ok = payload.get("ok")
    rc = payload.get("return_code")
    if not isinstance(ok, bool):
        return None
    if not isinstance(rc, int):
        return None

    out: JsonMap = {"ok": ok, "return_code": rc}
    lp = payload.get("log_path")
    jp = payload.get("json_path")
    if isinstance(lp, str) and lp:
        out["log_path"] = lp
    if isinstance(jp, str) and jp:
        out["json_path"] = jp
    return out


def _iter_socket_candidates(socket_path: Path) -> list[Path]:
    root_candidate = socket_path
    root_dir = socket_path.parent
    socket_name = socket_path.name

    candidates: list[Path] = [root_candidate]
    seen = {root_candidate}

    try:
        for path in sorted(root_dir.rglob(socket_name)):
            if path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    except FileNotFoundError:
        return candidates

    return candidates


def record_ipc_stream(
    socket_path: Path,
    *,
    out_path: Path,
    connect_timeout_s: float,
    total_timeout_s: float,
    command_plans: list[dict[str, object]] | None = None,
    result_json_copy_path: Path | None = None,
    runner_jsonl_copy_path: Path | None = None,
    runner_log_copy_path: Path | None = None,
    on_log_message: Callable[[str], None] | None = None,
) -> tuple[JsonMap | None, str, JsonMap]:
    """Record the full runner IPC NDJSON stream and compute runner value_text.

    Optional command_plans are executed over the same IPC connection so that
    stream recording and command/reply traffic can coexist even when the runner
    serves clients serially.
    """

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.open("w", encoding="utf-8", newline="\n").close()

    connect_deadline = time.monotonic() + max(0.0, float(connect_timeout_s))
    total_deadline: float | None
    if float(total_timeout_s) > 0:
        total_deadline = time.monotonic() + float(total_timeout_s)
    else:
        total_deadline = None

    s: socket.socket | None = None
    while True:
        if time.monotonic() >= connect_deadline:
            _finalize_unresolved_plans(
                _prepare_command_plans(command_plans or []),
                code="CONNECT_TIMEOUT",
                message="ipc connect timeout",
            )
            return None, "", _result_artifact_copy_status(error=None)
        connected = False
        for candidate in _iter_socket_candidates(socket_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.2)
                s.connect(str(candidate))
                connected = True
                break
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                with contextlib.suppress(Exception):
                    if s is not None:
                        s.close()
                s = None
                continue
        if connected:
            break
        time.sleep(0.005)

    value_msgs: list[str] = []
    result: JsonMap | None = None
    plans = _prepare_command_plans(command_plans or [])
    connected_at = time.monotonic()

    artifact_copy_error: str | None = None

    def _handle_obj(obj: JsonMap) -> None:
        nonlocal artifact_copy_error, result
        if obj.get("type") == "log":
            msg = obj.get("msg")
            if isinstance(msg, str):
                value_msgs.append(msg)
                if on_log_message is not None:
                    on_log_message(msg)
        if obj.get("type") == "result":
            valid = _validate_result(obj)
            if valid is not None:
                result = valid
                if artifact_copy_error is None:
                    artifact_copy_error = _copy_result_artifact(
                        valid,
                        result_json_copy_path=result_json_copy_path,
                        runner_jsonl_copy_path=runner_jsonl_copy_path,
                        runner_log_copy_path=runner_log_copy_path,
                    )
        for plan in plans:
            if plan.matched_event is not None:
                continue
            evt_type = plan.wait_event_type
            evt_name = plan.wait_event_name
            if evt_type is None and evt_name is None:
                continue
            if evt_type is not None and str(obj.get("type", "")) != evt_type:
                continue
            if evt_name is not None and str(obj.get("event", "")) != evt_name:
                continue
            plan.matched_event = obj
        if obj.get("type") == "reply":
            cmd_id = str(obj.get("cmd_id", ""))
            for plan in plans:
                if plan.sent and not plan.done and plan.cmd_id == cmd_id:
                    _write_json(plan.reply_path, obj)
                    plan.done = True
                    break

    assert s is not None

    try:
        s.setblocking(False)
        pending = ""
        with out_path.open("a", encoding="utf-8", newline="\n") as out_fp:
            while True:
                _maybe_send_ready_commands(s, plans, connected_at)
                if total_deadline is None:
                    wait_s: float | None = 0.05
                else:
                    wait_s = max(0.0, min(0.05, total_deadline - time.monotonic()))
                    if wait_s == 0.0:
                        break

                try:
                    readable = _wait_socket_readable(s, wait_s)
                except OSError:
                    break
                if readable:
                    try:
                        chunk = s.recv(65536)
                    except BlockingIOError:
                        chunk = b""
                    except OSError:
                        break
                    if chunk == b"":
                        break
                    pending += chunk.decode("utf-8", errors="replace")
                    while True:
                        newline_at = pending.find("\n")
                        if newline_at < 0:
                            break
                        line = pending[: newline_at + 1]
                        pending = pending[newline_at + 1 :]
                        out_fp.write(line)
                        try:
                            parsed: object = json.loads(line)
                        except Exception:
                            continue
                        obj = _to_json_map(parsed)
                        if obj is not None:
                            _handle_obj(obj)

                _maybe_send_waiting_commands(s, plans, connected_at)
                if result is not None and all(plan.done for plan in plans):
                    if total_deadline is None:
                        extra_deadline = time.monotonic() + 0.2
                        while time.monotonic() < extra_deadline:
                            try:
                                readable = _wait_socket_readable(s, 0.02)
                            except OSError:
                                readable = False
                            if not readable:
                                break
                            try:
                                chunk = s.recv(65536)
                            except (BlockingIOError, OSError):
                                break
                            if not chunk:
                                break
                            pending += chunk.decode("utf-8", errors="replace")
                            while True:
                                newline_at = pending.find("\n")
                                if newline_at < 0:
                                    break
                                line = pending[: newline_at + 1]
                                pending = pending[newline_at + 1 :]
                                out_fp.write(line)
                                try:
                                    parsed_extra: object = json.loads(line)
                                except Exception:
                                    continue
                                obj = _to_json_map(parsed_extra)
                                if obj is not None:
                                    _handle_obj(obj)
                    break

            if pending:
                out_fp.write(pending)
                try:
                    parsed_pending: object = json.loads(pending)
                except Exception:
                    parsed_pending = None
                obj = _to_json_map(parsed_pending)
                if obj is not None:
                    _handle_obj(obj)
    finally:
        with contextlib.suppress(Exception):
            s.close()

    _finalize_unresolved_plans(plans, code="EOF", message="ipc connection closed before reply")
    value_text = "\n".join(value_msgs)
    return result, value_text, _result_artifact_copy_status(error=artifact_copy_error)


def _prepare_command_plans(raw_plans: list[dict[str, object]]) -> list[PreparedCommandPlan]:
    plans: list[PreparedCommandPlan] = []
    for item in raw_plans:
        protocol = str(item.get("protocol", "am_patch_ipc/1"))
        cmd = str(item.get("cmd", "")).strip()
        if not cmd:
            continue
        cmd_id = str(item.get("cmd_id", "")).strip()
        if not cmd_id:
            continue

        args_obj = item.get("args", {})
        args_map = _to_json_map(args_obj)
        args = args_map if args_map is not None else {}

        delay_raw = item.get("delay_s", 0.0)
        if isinstance(delay_raw, bool) or not isinstance(delay_raw, int | float):
            delay_s = 0.0
        else:
            delay_s = float(delay_raw)

        wait_event_type_obj = item.get("wait_event_type")
        wait_event_type = (
            str(wait_event_type_obj).strip() if isinstance(wait_event_type_obj, str) else None
        )
        if wait_event_type == "":
            wait_event_type = None

        wait_event_name_obj = item.get("wait_event_name")
        wait_event_name = (
            str(wait_event_name_obj).strip() if isinstance(wait_event_name_obj, str) else None
        )
        if wait_event_name == "":
            wait_event_name = None

        raw_map = item.get("event_arg_map", {})
        raw_map_obj = _to_json_map(raw_map)
        event_arg_map: dict[str, str] = {}
        if raw_map_obj is not None:
            for key, value in raw_map_obj.items():
                if isinstance(value, str):
                    event_arg_map[key] = value

        request_path_raw = item.get("request_path")
        reply_path_raw = item.get("reply_path")
        if not isinstance(request_path_raw, Path) or not isinstance(reply_path_raw, Path):
            continue

        plans.append(
            PreparedCommandPlan(
                protocol=protocol,
                cmd=cmd,
                cmd_id=cmd_id,
                args=args,
                delay_s=delay_s,
                wait_event_type=wait_event_type,
                wait_event_name=wait_event_name,
                event_arg_map=event_arg_map,
                request_path=request_path_raw,
                reply_path=reply_path_raw,
            )
        )
    return plans


def _maybe_send_ready_commands(
    sock: socket.socket,
    plans: list[PreparedCommandPlan],
    connected_at: float,
) -> None:
    _maybe_send_waiting_commands(sock, plans, connected_at)


def _maybe_send_waiting_commands(
    sock: socket.socket,
    plans: list[PreparedCommandPlan],
    connected_at: float,
) -> None:
    now = time.monotonic()
    for plan in plans:
        if plan.sent or plan.done:
            continue
        evt_type = plan.wait_event_type
        evt_name = plan.wait_event_name
        matched_event = plan.matched_event
        if (evt_type is not None or evt_name is not None) and matched_event is None:
            continue
        if now < connected_at + max(0.0, plan.delay_s):
            continue
        args = dict(plan.args)
        if matched_event is not None:
            for arg_name, field_name in plan.event_arg_map.items():
                args[arg_name] = matched_event.get(field_name)
        request: JsonMap = {
            "protocol": plan.protocol,
            "type": "cmd",
            "cmd": plan.cmd,
            "cmd_id": plan.cmd_id,
            "args": args,
        }
        _write_json(plan.request_path, request)
        try:
            sock.sendall(_json_line(request))
            plan.sent = True
        except OSError:
            _write_json(
                plan.reply_path,
                {
                    "ok": False,
                    "error": {
                        "code": "SEND_ERROR",
                        "message": "ipc command send failed",
                    },
                },
            )
            plan.done = True


def _finalize_unresolved_plans(
    plans: list[PreparedCommandPlan],
    *,
    code: str,
    message: str,
) -> None:
    for plan in plans:
        if plan.done:
            continue
        if not plan.sent and (plan.wait_event_type is not None or plan.wait_event_name is not None):
            _write_json(
                plan.reply_path,
                {
                    "ok": False,
                    "error": {
                        "code": "EVENT_TIMEOUT",
                        "message": "ipc stream event not observed",
                    },
                },
            )
        else:
            _write_json(
                plan.reply_path,
                {
                    "ok": False,
                    "error": {
                        "code": code,
                        "message": message,
                    },
                },
            )
        plan.done = True


def _json_line(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
