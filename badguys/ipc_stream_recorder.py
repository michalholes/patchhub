from __future__ import annotations

import contextlib
import json
import select
import shutil
import socket
import time
from pathlib import Path
from typing import Any


def _copy_result_artifact(
    result: dict[str, Any],
    *,
    result_json_copy_path: Path | None,
    runner_jsonl_copy_path: Path | None,
    runner_log_copy_path: Path | None,
) -> tuple[str | None, bool]:
    runner_jsonl_missing = False

    if result_json_copy_path is not None:
        try:
            _write_json(result_json_copy_path, result)
        except OSError as exc:
            return f"write runner result failed: {result_json_copy_path}: {exc}", False

    json_path = result.get("json_path")
    if runner_jsonl_copy_path is not None and isinstance(json_path, str) and json_path:
        err, missing_source = _copy_result_artifact_path(
            src_path=json_path,
            dst_path=runner_jsonl_copy_path,
            label="json_path",
        )
        runner_jsonl_missing = missing_source
        if err is not None:
            return err, runner_jsonl_missing

    log_path = result.get("log_path")
    if runner_log_copy_path is not None and isinstance(log_path, str) and log_path:
        err, _ = _copy_result_artifact_path(
            src_path=log_path,
            dst_path=runner_log_copy_path,
            label="log_path",
        )
        if err is not None:
            return err, runner_jsonl_missing
    return None, runner_jsonl_missing


def _copy_result_artifact_path(
    *,
    src_path: str,
    dst_path: Path,
    label: str,
) -> tuple[str | None, bool]:
    src = Path(src_path)
    if not src.exists():
        return f"missing runner {label}: {src}", True
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst_path)
    except FileNotFoundError:
        return f"missing runner {label}: {src}", True
    except OSError as exc:
        return f"copy runner {label} failed: {src} -> {dst_path}: {exc}", False
    return None, False


def _result_artifact_copy_status(*, error: str | None) -> dict[str, Any]:
    return {"ok": error is None, "error": error}


def _copy_ipc_stream_fallback(*, out_path: Path, dst_path: Path) -> str | None:
    if not out_path.exists():
        return f"missing ipc stream for runner json_path fallback: {out_path}"
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(out_path, dst_path)
    except OSError as exc:
        return f"copy runner json_path fallback failed: {out_path} -> {dst_path}: {exc}"
    return None


def _validate_result(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    if "ok" not in obj or "return_code" not in obj:
        return None
    ok = obj.get("ok")
    rc = obj.get("return_code")
    if not isinstance(ok, bool):
        return None
    if not isinstance(rc, int):
        return None

    out: dict[str, Any] = {"ok": ok, "return_code": rc}
    lp = obj.get("log_path")
    jp = obj.get("json_path")
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
    command_plans: list[dict[str, Any]] | None = None,
    result_json_copy_path: Path | None = None,
    runner_jsonl_copy_path: Path | None = None,
    runner_log_copy_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
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
    result: dict[str, Any] | None = None
    plans = _prepare_command_plans(command_plans or [])
    connected_at = time.monotonic()

    artifact_copy_error: str | None = None
    runner_jsonl_missing = False

    def _handle_obj(obj: dict[str, Any]) -> None:
        nonlocal artifact_copy_error, result, runner_jsonl_missing
        if obj.get("type") == "log":
            msg = obj.get("msg")
            if isinstance(msg, str):
                value_msgs.append(msg)
        if obj.get("type") == "result":
            valid = _validate_result(obj)
            if valid is not None:
                result = valid
                if artifact_copy_error is None:
                    artifact_copy_error, runner_jsonl_missing = _copy_result_artifact(
                        valid,
                        result_json_copy_path=result_json_copy_path,
                        runner_jsonl_copy_path=runner_jsonl_copy_path,
                        runner_log_copy_path=runner_log_copy_path,
                    )
        for plan in plans:
            if plan["matched_event"] is not None:
                continue
            evt_type = plan["wait_event_type"]
            evt_name = plan["wait_event_name"]
            if evt_type is None and evt_name is None:
                continue
            if evt_type is not None and str(obj.get("type", "")) != evt_type:
                continue
            if evt_name is not None and str(obj.get("event", "")) != evt_name:
                continue
            plan["matched_event"] = obj
        if obj.get("type") == "reply":
            cmd_id = str(obj.get("cmd_id", ""))
            for plan in plans:
                if plan["sent"] and not plan["done"] and str(plan["cmd_id"]) == cmd_id:
                    _write_json(plan["reply_path"], obj)
                    plan["done"] = True
                    break

    if s is None:
        _finalize_unresolved_plans(plans, code="CONNECT_TIMEOUT", message="ipc connect timeout")
        return None, "", _result_artifact_copy_status(error=None)

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
                    readable, _, _ = select.select([s], [], [], wait_s)
                except (OSError, ValueError):
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
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if isinstance(obj, dict):
                            _handle_obj(obj)

                _maybe_send_waiting_commands(s, plans, connected_at)
                if result is not None and all(plan["done"] for plan in plans):
                    if total_deadline is None:
                        extra_deadline = time.monotonic() + 0.2
                        while time.monotonic() < extra_deadline:
                            try:
                                readable, _, _ = select.select([s], [], [], 0.02)
                            except (OSError, ValueError):
                                readable = []
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
                                    obj = json.loads(line)
                                except Exception:
                                    continue
                                if isinstance(obj, dict):
                                    _handle_obj(obj)
                    break

            if pending:
                out_fp.write(pending)
                try:
                    obj = json.loads(pending)
                except Exception:
                    obj = None
                if isinstance(obj, dict):
                    _handle_obj(obj)
    finally:
        with contextlib.suppress(Exception):
            if s is not None:
                s.close()

    _finalize_unresolved_plans(plans, code="EOF", message="ipc connection closed before reply")
    if (
        runner_jsonl_missing
        and artifact_copy_error is not None
        and runner_jsonl_copy_path is not None
    ):
        artifact_copy_error = _copy_ipc_stream_fallback(
            out_path=out_path,
            dst_path=runner_jsonl_copy_path,
        )
    value_text = "\n".join(value_msgs)
    return result, value_text, _result_artifact_copy_status(error=artifact_copy_error)


def _prepare_command_plans(raw_plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for item in raw_plans:
        plan = dict(item)
        plan.setdefault("args", {})
        plan.setdefault("delay_s", 0.0)
        plan.setdefault("wait_event_type", None)
        plan.setdefault("wait_event_name", None)
        plan.setdefault("event_arg_map", {})
        plan["matched_event"] = None
        plan["sent"] = False
        plan["done"] = False
        plans.append(plan)
    return plans


def _maybe_send_ready_commands(
    sock: socket.socket,
    plans: list[dict[str, Any]],
    connected_at: float,
) -> None:
    _maybe_send_waiting_commands(sock, plans, connected_at)


def _maybe_send_waiting_commands(
    sock: socket.socket,
    plans: list[dict[str, Any]],
    connected_at: float,
) -> None:
    now = time.monotonic()
    for plan in plans:
        if plan["sent"] or plan["done"]:
            continue
        evt_type = plan["wait_event_type"]
        evt_name = plan["wait_event_name"]
        matched_event = plan["matched_event"]
        if (evt_type is not None or evt_name is not None) and matched_event is None:
            continue
        if now < connected_at + float(plan.get("delay_s", 0.0) or 0.0):
            continue
        args = dict(plan.get("args", {}))
        if matched_event is not None:
            for arg_name, field_name in dict(plan.get("event_arg_map", {})).items():
                args[arg_name] = matched_event.get(field_name)
        request = {
            "protocol": plan["protocol"],
            "type": "cmd",
            "cmd": plan["cmd"],
            "cmd_id": plan["cmd_id"],
            "args": args,
        }
        _write_json(plan["request_path"], request)
        try:
            sock.sendall(_json_line(request))
            plan["sent"] = True
        except OSError:
            _write_json(
                plan["reply_path"],
                {
                    "ok": False,
                    "error": {
                        "code": "SEND_ERROR",
                        "message": "ipc command send failed",
                    },
                },
            )
            plan["done"] = True


def _finalize_unresolved_plans(plans: list[dict[str, Any]], *, code: str, message: str) -> None:
    for plan in plans:
        if plan.get("done"):
            continue
        if not plan.get("sent") and (
            plan.get("wait_event_type") is not None or plan.get("wait_event_name") is not None
        ):
            _write_json(
                plan["reply_path"],
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
                plan["reply_path"],
                {
                    "ok": False,
                    "error": {
                        "code": code,
                        "message": message,
                    },
                },
            )
        plan["done"] = True


def _json_line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
