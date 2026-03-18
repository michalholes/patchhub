from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch.errors import RunnerError

PROTOCOL = "am_patch_ipc/1"

_LEVELS = ("quiet", "normal", "warning", "verbose", "debug")

_STARTUP_EXISTS_MODE = "fail"
_STARTUP_WAIT_S = 0


def _normalize_level(v: str) -> str:
    lvl = str(v or "").strip().lower()
    return lvl if lvl in _LEVELS else "verbose"


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            path.unlink()
    except Exception:
        pass


def _json_line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


def _system_runtime_dir() -> Path:
    uid = os.getuid()
    candidates = [
        Path("/run/user") / str(uid),
        Path("/run"),
        Path("/tmp"),
    ]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            test = c / ".am_patch_ipc_probe"
            test.write_text("x", encoding="utf-8")
            test.unlink()
            return c
        except Exception:
            continue
    return Path(".")


def _sanitize_filename(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return "am_patch_ipc_none_0.sock"
    out: list[str] = []
    for ch in s:
        if ch.isalnum() or ch in "._-":
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out)
    if "/" in cleaned or "\\" in cleaned or cleaned in (".", ".."):
        return "am_patch_ipc_none_0.sock"
    return cleaned


def _render_template(tpl: str, *, issue_id: str | None, pid: int) -> str:
    issue = str(issue_id or "none")
    issue = _sanitize_filename(issue)
    try:
        rendered = str(tpl).format(issue=issue, pid=int(pid))
    except Exception:
        rendered = f"am_patch_ipc_{issue}_{pid}.sock"
    return _sanitize_filename(rendered)


@dataclass
class IpcState:
    paused: bool = False
    cancel: bool = False
    stop_after_step: str | None = None
    pause_after_step: str | None = None


@dataclass
class _IpcClient:
    conn: socket.socket
    write_lock: threading.Lock


class IpcController:
    def __init__(
        self,
        *,
        socket_path: Path,
        issue_id: str | None,
        mode: str,
        status_provider: Any,
        logger: Any,
        handshake_enabled: bool = False,
        handshake_wait_s: int = 0,
    ) -> None:
        self.socket_path = socket_path
        self.issue_id = issue_id
        self.mode = mode
        self._status_provider = status_provider
        self._logger = logger

        self._state = IpcState()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._thread: threading.Thread | None = None

        self._clients_lock = threading.Lock()
        self._clients: list[_IpcClient] = []

        self._handshake_enabled = bool(handshake_enabled)
        self._handshake_wait_s = max(0, int(handshake_wait_s or 0))
        self._startup_ready = threading.Event()
        self._drain_ack = threading.Event()
        self._startup_state = "pending" if self._handshake_enabled else "disabled"
        self._expected_drain_seq: int | None = None

        set_stream = getattr(self._logger, "set_ipc_stream", None)
        if callable(set_stream):
            set_stream(self._on_log_event)

    def start(self) -> None:
        if self._thread is not None:
            return self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            mode = str(_STARTUP_EXISTS_MODE or "fail").strip() or "fail"
            wait_s = int(_STARTUP_WAIT_S or 0)
            if wait_s < 0:
                wait_s = 0
            if mode == "wait_then_fail" and wait_s:
                threading.Event().wait(float(wait_s))
            if mode == "unlink_if_stale":
                active = False
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    try:
                        s.settimeout(0.2)
                        s.connect(str(self.socket_path))
                        active = True
                    finally:
                        with contextlib.suppress(Exception):
                            s.close()
                except Exception:
                    active = False
                if not active:
                    _safe_unlink(self.socket_path)
                else:
                    raise RunnerError(
                        "IPC",
                        "SOCKET_EXISTS",
                        (
                            f"socket path exists and is active: {self.socket_path}\n"
                            "Hint: stop the other runner or choose a different socket name."
                        ),
                    )
            if self.socket_path.exists() or self.socket_path.is_symlink():
                raise RunnerError(
                    "IPC",
                    "SOCKET_EXISTS",
                    (
                        f"socket path exists: {self.socket_path}\n"
                        "Hint: remove stale socket or set "
                        "ipc_socket_on_startup_exists=unlink_if_stale."
                    ),
                )
        self._thread = threading.Thread(target=self._serve, name="am_patch_ipc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()
        self._startup_ready.set()
        self._drain_ack.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            with contextlib.suppress(Exception):
                client.conn.close()
        _safe_unlink(self.socket_path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            st = IpcState(
                paused=self._state.paused,
                cancel=self._state.cancel,
                stop_after_step=self._state.stop_after_step,
                pause_after_step=self._state.pause_after_step,
            )
        stage = "PREFLIGHT"
        try:
            stage = str(self._status_provider.get_stage() or "PREFLIGHT")
        except Exception:
            stage = "PREFLIGHT"
        return {
            "protocol": PROTOCOL,
            "issue_id": self.issue_id,
            "mode": self.mode,
            "stage": stage,
            "paused": st.paused,
            "cancel": st.cancel,
            "stop_after_step": st.stop_after_step,
            "pause_after_step": st.pause_after_step,
            "verbosity": getattr(self._logger, "screen_level", "verbose"),
            "log_level": getattr(self._logger, "log_level", "verbose"),
        }

    def request_cancel(self) -> None:
        with self._lock:
            self._state.cancel = True
        cancel_active = getattr(self._logger, "request_subprocess_cancel", None)
        if callable(cancel_active):
            with contextlib.suppress(Exception):
                cancel_active()
        self._resume.set()

    def request_resume(self) -> None:
        with self._lock:
            paused = self._state.paused
            self._state.paused = False
        self._resume.set()
        if paused:
            self._emit_control("resumed")

    def set_stop_after_step(self, step: str | None) -> None:
        with self._lock:
            self._state.stop_after_step = str(step).strip() if step else None

    def set_pause_after_step(self, step: str | None) -> None:
        with self._lock:
            self._state.pause_after_step = str(step).strip() if step else None

    def set_verbosity(self, *, verbosity: str | None = None, log_level: str | None = None) -> None:
        if verbosity is not None:
            self._logger.screen_level = _normalize_level(verbosity)
        if log_level is not None:
            self._logger.log_level = _normalize_level(log_level)

    def check_boundary(self, *, completed_step: str) -> str | None:
        step = str(completed_step or "").strip()
        if not step:
            return None
        paused_now = False
        with self._lock:
            if self._state.cancel:
                return "cancel"
            if self._state.stop_after_step and self._state.stop_after_step == step:
                self._state.cancel = True
                return "stop_after_step"
            if self._state.pause_after_step and self._state.pause_after_step == step:
                self._state.paused = True
                self._resume.clear()
                paused_now = True

        if paused_now:
            self._emit_control("paused", {"step": step})
            return "pause_after_step"
        return None

    def wait_if_paused(self) -> None:
        while True:
            with self._lock:
                paused = self._state.paused
                cancelled = self._state.cancel
            if cancelled or not paused:
                return
            self._resume.wait(0.25)

    def wait_for_ready(self) -> bool:
        if not self._handshake_enabled:
            return False
        ready = self._startup_ready.wait(float(self._handshake_wait_s))
        with self._lock:
            if ready:
                self._startup_state = "completed"
            elif self._startup_state == "pending":
                self._startup_state = "timed_out"
        return ready

    def startup_handshake_completed(self) -> bool:
        with self._lock:
            return self._startup_state == "completed"

    def begin_shutdown_handshake(self, *, eos_seq: int) -> bool:
        if not self._handshake_enabled:
            return False
        with self._lock:
            if self._startup_state != "completed":
                return False
            self._expected_drain_seq = int(eos_seq)
            self._drain_ack.clear()
            return True

    def wait_for_drain_ack(self) -> bool:
        with self._lock:
            if self._expected_drain_seq is None:
                return False
        return self._drain_ack.wait(float(self._handshake_wait_s))

    def _emit_control(self, event: str, data: dict[str, Any] | None = None) -> None:
        emit = getattr(self._logger, "emit_control_event", None)
        if not callable(emit):
            return
        payload: dict[str, Any] = {"type": "control", "event": str(event or "")}
        if data:
            payload.update(data)
        with contextlib.suppress(Exception):
            emit(payload)

    def _drop_client(self, client: _IpcClient) -> None:
        with self._clients_lock:
            self._clients = [entry for entry in self._clients if entry is not client]
        with contextlib.suppress(Exception):
            client.conn.close()

    def _write_client_line(self, client: _IpcClient, line: bytes) -> None:
        with client.write_lock:
            client.conn.sendall(line)

    def _recv_line(self, client: _IpcClient, pending: bytearray) -> bytes | None:
        while True:
            nl = pending.find(b"\n")
            if nl >= 0:
                line = bytes(pending[: nl + 1])
                del pending[: nl + 1]
                return line
            try:
                chunk = client.conn.recv(4096)
            except TimeoutError as exc:
                raise TimeoutError from exc
            if not chunk:
                return None
            pending.extend(chunk)

    def _on_log_event(self, evt: dict[str, Any]) -> None:
        line = _json_line(evt)
        with self._clients_lock:
            clients = list(self._clients)
        failed: list[_IpcClient] = []
        for client in clients:
            try:
                self._write_client_line(client, line)
            except Exception:
                failed.append(client)
        for client in failed:
            self._drop_client(client)

    def _reply_ok(self, *, cmd_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "type": "reply",
            "cmd_id": cmd_id,
            "ok": True,
            "data": data or {},
        }

    def _reply_err(self, *, cmd_id: str, code: str, message: str) -> dict[str, Any]:
        return {
            "type": "reply",
            "cmd_id": cmd_id,
            "ok": False,
            "error": {"code": str(code or "ERROR"), "message": str(message or "")},
        }

    def _send_reply(
        self,
        client: _IpcClient,
        *,
        cmd_id: str,
        ok: bool,
        data: dict[str, Any] | None = None,
        code: str = "",
        message: str = "",
    ) -> None:
        payload = (
            self._reply_ok(cmd_id=cmd_id, data=data)
            if ok
            else self._reply_err(cmd_id=cmd_id, code=code, message=message)
        )
        self._write_client_line(client, _json_line(payload))

    def _serve(self) -> None:
        sock_path = self.socket_path
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(str(sock_path))
            srv.listen(5)
            srv.settimeout(0.25)
        except Exception:
            with contextlib.suppress(Exception):
                srv.close()
            return

        while not self._stop.is_set():
            try:
                conn, _addr = srv.accept()
            except TimeoutError:
                continue
            except Exception:
                break

            conn.settimeout(1.0)
            client = _IpcClient(conn=conn, write_lock=threading.Lock())
            pending = bytearray()
            with self._clients_lock:
                self._clients.append(client)

            self._write_client_line(
                client,
                _json_line({"type": "control", "event": "connected", **self.snapshot()}),
            )

            try:
                while not self._stop.is_set():
                    try:
                        line = self._recv_line(client, pending)
                    except TimeoutError:
                        continue
                    except Exception:
                        break
                    if line is None:
                        break
                    raw = line.strip()
                    if not raw:
                        continue

                    try:
                        req = json.loads(raw.decode("utf-8", errors="strict"))
                    except Exception:
                        self._send_reply(
                            client,
                            cmd_id="",
                            ok=False,
                            code="BAD_JSON",
                            message="bad json",
                        )
                        continue

                    if not isinstance(req, dict):
                        self._send_reply(
                            client,
                            cmd_id="",
                            ok=False,
                            code="VALIDATION_ERROR",
                            message="request must be an object",
                        )
                        continue

                    if "protocol" in req and str(req.get("protocol", "")) != PROTOCOL:
                        cmd_id = str(req.get("cmd_id", "") or "")
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=False,
                            code="BAD_PROTOCOL",
                            message="bad protocol",
                        )
                        continue

                    if str(req.get("type", "")) != "cmd":
                        cmd_id = str(req.get("cmd_id", "") or "")
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=False,
                            code="VALIDATION_ERROR",
                            message="missing type=cmd",
                        )
                        continue

                    cmd_id = str(req.get("cmd_id", "") or "").strip()
                    if not cmd_id:
                        self._send_reply(
                            client,
                            cmd_id="",
                            ok=False,
                            code="VALIDATION_ERROR",
                            message="missing cmd_id",
                        )
                        continue

                    cmd = str(req.get("cmd", "") or "").strip()
                    args = req.get("args")
                    if args is None:
                        args = {}
                    if not isinstance(args, dict):
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=False,
                            code="VALIDATION_ERROR",
                            message="args must be an object",
                        )
                        continue

                    if cmd == "ping":
                        self._send_reply(client, cmd_id=cmd_id, ok=True, data={"pong": True})
                        continue

                    if cmd == "get_state":
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=True,
                            data=self.snapshot(),
                        )
                        continue

                    if cmd == "cancel":
                        self.request_cancel()
                        self._send_reply(client, cmd_id=cmd_id, ok=True)
                        continue

                    if cmd == "stop_after_step":
                        step = args.get("step")
                        self.set_stop_after_step(str(step) if step is not None else None)
                        self._send_reply(client, cmd_id=cmd_id, ok=True)
                        continue

                    if cmd == "pause_after_step":
                        step = args.get("step")
                        self.set_pause_after_step(str(step) if step is not None else None)
                        self._send_reply(client, cmd_id=cmd_id, ok=True)
                        continue

                    if cmd == "resume":
                        with self._lock:
                            paused = self._state.paused
                        if not paused:
                            self._send_reply(
                                client,
                                cmd_id=cmd_id,
                                ok=False,
                                code="INVALID_STATE",
                                message="runner is not paused",
                            )
                            continue
                        self.request_resume()
                        self._send_reply(client, cmd_id=cmd_id, ok=True)
                        continue

                    if cmd == "set_verbosity":
                        v = args.get("verbosity")
                        ll = args.get("log_level")
                        self.set_verbosity(
                            verbosity=(str(v) if v is not None else None),
                            log_level=(str(ll) if ll is not None else None),
                        )
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=True,
                            data={
                                "verbosity": getattr(self._logger, "screen_level", "verbose"),
                                "log_level": getattr(self._logger, "log_level", "verbose"),
                            },
                        )
                        continue

                    if cmd == "ready":
                        if not self._handshake_enabled:
                            self._send_reply(
                                client,
                                cmd_id=cmd_id,
                                ok=False,
                                code="INVALID_STATE",
                                message="startup handshake is disabled",
                            )
                            continue
                        with self._lock:
                            state = self._startup_state
                            if state == "pending":
                                self._startup_state = "completed"
                                self._startup_ready.set()
                            elif state != "completed":
                                self._send_reply(
                                    client,
                                    cmd_id=cmd_id,
                                    ok=False,
                                    code="INVALID_STATE",
                                    message="startup handshake is not active",
                                )
                            else:
                                self._send_reply(
                                    client,
                                    cmd_id=cmd_id,
                                    ok=True,
                                    data={"ready": True},
                                )
                                continue
                        if state == "pending":
                            self._send_reply(
                                client,
                                cmd_id=cmd_id,
                                ok=True,
                                data={"ready": True},
                            )
                        continue

                    if cmd == "drain_ack":
                        raw_seq = args.get("seq")
                        if raw_seq is None:
                            self._send_reply(
                                client,
                                cmd_id=cmd_id,
                                ok=False,
                                code="VALIDATION_ERROR",
                                message="drain_ack seq must be an integer",
                            )
                            continue
                        try:
                            ack_seq = int(raw_seq)
                        except Exception:
                            self._send_reply(
                                client,
                                cmd_id=cmd_id,
                                ok=False,
                                code="VALIDATION_ERROR",
                                message="drain_ack seq must be an integer",
                            )
                            continue
                        with self._lock:
                            if self._startup_state != "completed":
                                self._send_reply(
                                    client,
                                    cmd_id=cmd_id,
                                    ok=False,
                                    code="INVALID_STATE",
                                    message="startup handshake did not complete",
                                )
                                continue
                            expected = self._expected_drain_seq
                            if expected is None:
                                self._send_reply(
                                    client,
                                    cmd_id=cmd_id,
                                    ok=False,
                                    code="INVALID_STATE",
                                    message="eos was not emitted",
                                )
                                continue
                            if ack_seq != expected:
                                self._send_reply(
                                    client,
                                    cmd_id=cmd_id,
                                    ok=False,
                                    code="VALIDATION_ERROR",
                                    message=f"expected seq={expected}",
                                )
                                continue
                            self._drain_ack.set()
                        self._send_reply(
                            client,
                            cmd_id=cmd_id,
                            ok=True,
                            data={"seq": ack_seq},
                        )
                        continue

                    self._send_reply(
                        client,
                        cmd_id=cmd_id,
                        ok=False,
                        code="UNKNOWN_CMD",
                        message="unknown cmd",
                    )
            finally:
                self._drop_client(client)

        with contextlib.suppress(Exception):
            srv.close()
        _safe_unlink(sock_path)


def resolve_socket_path(*, policy: Any, patch_dir: Path, issue_id: str | None) -> Path | None:
    global _STARTUP_EXISTS_MODE, _STARTUP_WAIT_S
    _STARTUP_EXISTS_MODE = (
        str(getattr(policy, "ipc_socket_on_startup_exists", _STARTUP_EXISTS_MODE)).strip() or "fail"
    )
    try:
        _STARTUP_WAIT_S = int(getattr(policy, "ipc_socket_on_startup_wait_s", 0) or 0)
    except Exception:
        _STARTUP_WAIT_S = 0

    enabled = bool(getattr(policy, "ipc_socket_enabled", True))
    if not enabled:
        return None

    explicit = getattr(policy, "ipc_socket_path", None)
    if explicit:
        return Path(str(explicit))

    mode = str(getattr(policy, "ipc_socket_mode", "patch_dir") or "patch_dir").strip().lower()
    tpl = str(getattr(policy, "ipc_socket_name_template", "") or "").strip()
    if not tpl:
        tpl = "am_patch_ipc_{issue}_{pid}.sock"

    name = _render_template(tpl, issue_id=issue_id, pid=os.getpid())

    if mode == "patch_dir":
        return patch_dir / name

    if mode == "base_dir":
        base = getattr(policy, "ipc_socket_base_dir", None)
        if not base:
            return None
        return Path(str(base)) / name

    if mode == "system_runtime":
        base = getattr(policy, "ipc_socket_system_runtime_dir", None)
        if base:
            return Path(str(base)) / name
        return _system_runtime_dir() / name

    return None
