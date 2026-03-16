from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .console import colorize_console_message, stdout_color_enabled
from .errors import RunnerCancelledError, RunnerError
from .final_summary import TerminalSummary, result_event_payload
from .managed_subprocess import ManagedSubprocess


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


Severity = str  # DEBUG|INFO|WARNING|ERROR
Channel = str  # CORE|DETAIL


_LEVELS = ("quiet", "normal", "warning", "verbose", "debug")
_SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR")
_CHANNELS = ("CORE", "DETAIL")


def _normalize_event_message(message: str) -> str:
    msg = message
    if msg.endswith("\n"):
        msg = msg[:-1]
    return msg


def _allowed(level: str, severity: Severity, channel: Channel, *, summary: bool) -> bool:
    """Return whether a message is allowed at a given level.

    Semantics are defined by the issue 999 handoff (shared for screen and log).

    Levels are inherited (each higher includes everything from the lower):

    - quiet:
        * START + RESULT only (summary=True bypass)
    - normal:
        * quiet + legacy concise flow lines (CORE)
    - warning:
        * normal + warnings (DETAIL+WARNING)
    - verbose:
        * warning + diagnostic sections (DETAIL+INFO)
    - debug:
        * verbose + DEBUG metadata (DETAIL+DEBUG)

    Full error detail (stdout/stderr) bypasses filtering and is handled
    via Logger.emit(..., error_detail=True).
    """

    lvl = (level or "").strip().lower()
    sev = (severity or "").strip().upper()
    ch = (channel or "").strip().upper()

    if lvl not in _LEVELS:
        lvl = "verbose"
    if sev not in _SEVERITIES:
        sev = "INFO"
    if ch not in _CHANNELS:
        ch = "DETAIL"

    if summary:
        return True

    if lvl == "quiet":
        return False

    if lvl == "normal":
        return ch == "CORE" and sev in ("INFO", "WARNING", "ERROR")

    if lvl == "warning":
        if ch == "CORE":
            return sev in ("INFO", "WARNING", "ERROR")
        return sev == "WARNING"

    if lvl == "verbose":
        if ch == "CORE":
            return sev in ("INFO", "WARNING", "ERROR")
        return sev in ("INFO", "WARNING")

    # debug
    return True


class Logger:
    def __init__(
        self,
        *,
        log_path: Path,
        symlink_path: Path,
        screen_level: str,
        log_level: str,
        console_color: str = "auto",
        symlink_enabled: bool = True,
        symlink_target_rel: Path | None = None,
        json_enabled: bool = False,
        json_path: Path | None = None,
        stage_provider: Callable[[], str] | None = None,
        run_timeout_s: int = 0,
    ) -> None:
        self.log_path = log_path
        self.symlink_path = symlink_path
        self.screen_level = str(screen_level or "").strip().lower() or "verbose"
        self.log_level = str(log_level or "").strip().lower() or "verbose"
        self.symlink_enabled = symlink_enabled
        self.symlink_target_rel = symlink_target_rel

        self.json_enabled = bool(json_enabled)
        self.json_path = json_path
        self._stage_provider = stage_provider
        self._json_fp = None
        self._close_stack = contextlib.ExitStack()
        self._json_seq = 0
        self.run_timeout_s = int(run_timeout_s or 0)
        self._mono_start = time.monotonic()

        self._ipc_hook: Callable[[str, str], None] | None = None
        self._screen_break_hook: Callable[[], None] | None = None

        self._ipc_stream: Callable[[dict[str, Any]], None] | None = None
        self._io_lock = threading.Lock()
        self._subprocess_lock = threading.Lock()
        self._active_subprocess: ManagedSubprocess | None = None

        self.console_color = str(console_color or "").strip().lower() or "auto"
        self._console_color_enabled = stdout_color_enabled(self.console_color)

        log_path.parent.mkdir(parents=True, exist_ok=True)
        symlink_path.parent.mkdir(parents=True, exist_ok=True)

        self._fp = self._close_stack.enter_context(
            log_path.open("w", encoding="utf-8", errors="replace")
        )

        if self.json_enabled and self.json_path is not None:
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            self._json_fp = self._close_stack.enter_context(
                self.json_path.open(
                    "w",
                    encoding="utf-8",
                    errors="replace",
                )
            )

        if self.symlink_enabled:
            try:
                if symlink_path.exists() or symlink_path.is_symlink():
                    symlink_path.unlink()
                target_rel = self.symlink_target_rel
                if target_rel is None:
                    target_rel = Path("logs") / log_path.name
                symlink_path.symlink_to(target_rel)
            except Exception:
                pass

    def set_ipc_hook(self, hook: Callable[[str, str], None] | None) -> None:
        self._ipc_hook = hook

    def set_ipc_stream(self, cb: Callable[[dict[str, Any]], None] | None) -> None:
        self._ipc_stream = cb

    def set_screen_break_hook(self, hook: Callable[[], None] | None) -> None:
        self._screen_break_hook = hook

    def close(self) -> None:
        try:
            self._fp.flush()
            if self._json_fp is not None:
                self._json_fp.flush()
        finally:
            self._close_stack.close()

    def _write_file(self, s: str) -> None:
        self._fp.write(s)
        self._fp.flush()

    def _write_screen(self, s: str) -> None:
        if self._console_color_enabled:
            with contextlib.suppress(Exception):
                s = colorize_console_message(s, enabled=True)
        sys.stdout.write(s)
        sys.stdout.flush()

    def _now_mono_ms(self) -> int:
        return int((time.monotonic() - self._mono_start) * 1000)

    def _get_stage(self) -> str:
        if self._stage_provider is None:
            return "PREFLIGHT"
        with contextlib.suppress(Exception):
            s = str(self._stage_provider() or "").strip()
            if s:
                return s
        return "PREFLIGHT"

    def _write_json(self, obj: dict[str, Any]) -> None:
        if self._json_fp is None:
            return
        line = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        self._json_fp.write(line + "\n")
        self._json_fp.flush()

    def emit(
        self,
        *,
        severity: Severity,
        channel: Channel,
        message: str,
        summary: bool = False,
        error_detail: bool = False,
        kind: str | None = None,
        to_screen: bool = True,
        to_log: bool = True,
        machine_event: bool = True,
    ) -> None:
        # One-line discipline: caller controls newlines.
        ipc_stream = self._ipc_stream
        need_evt = machine_event and (
            (self.json_enabled and self._json_fp is not None) or ipc_stream is not None
        )
        if need_evt:
            self._json_seq += 1
            msg = message
            if msg.endswith("\n"):
                msg = msg[:-1]
            evt = {
                "type": "log",
                "seq": self._json_seq,
                "ts_mono_ms": self._now_mono_ms(),
                "stage": self._get_stage(),
                "kind": kind or "TEXT",
                "sev": str(severity or "").strip().upper() or "INFO",
                "ch": str(channel or "").strip().upper() or "DETAIL",
                "summary": bool(summary),
                "bypass": bool(error_detail),
                "msg": msg,
            }
            if self.json_enabled and self._json_fp is not None:
                with contextlib.suppress(Exception):
                    self._write_json(evt)
            if ipc_stream is not None:
                with contextlib.suppress(Exception):
                    ipc_stream(evt)

        if to_log and (
            error_detail or _allowed(self.log_level, severity, channel, summary=summary)
        ):
            self._write_file(message)
        if to_screen and (
            error_detail or _allowed(self.screen_level, severity, channel, summary=summary)
        ):
            self._write_screen(message)

        hook = self._ipc_hook
        if hook is not None and kind in ("OK", "FAIL"):
            # "OK: STAGE" or "FAIL: STAGE"
            line = message.strip()
            _k, _sep, stage = line.partition(":")
            stage = stage.strip() if _sep else ""
            if stage:
                hook(kind, stage)

    def request_subprocess_cancel(self) -> bool:
        with self._subprocess_lock:
            active = self._active_subprocess
        if active is None:
            return False
        active.request_cancel()
        return True

    def _set_active_subprocess(self, managed: ManagedSubprocess | None) -> None:
        with self._subprocess_lock:
            self._active_subprocess = managed

    def _cancel_runner_error(self, *, argv: list[str]) -> RunnerCancelledError:
        stage = self._get_stage().strip() or "INTERNAL"
        cmd0 = str(argv[0]) if argv else "subprocess"
        return RunnerCancelledError(stage, f"subprocess canceled ({cmd0})")

    def _timeout_runner_error(
        self,
        *,
        timeout_s: int,
        timeout_stage: str | None,
        timeout_category: str,
        timeout_message: str | None,
        argv: list[str],
    ) -> RunnerError:
        stage = (timeout_stage or self._get_stage()).strip() or "PREFLIGHT"
        category = str(timeout_category or "TIMEOUT").strip() or "TIMEOUT"
        cmd0 = str(argv[0]) if argv else "subprocess"
        if timeout_message is not None:
            return RunnerError(stage, category, timeout_message)
        if stage.startswith("GATE_"):
            gate = stage[len("GATE_") :].strip().lower() or cmd0
            return RunnerError(
                "GATES",
                category,
                f"gate failed: {gate} (subprocess timeout after {timeout_s}s)",
            )
        if stage == "PATCH_APPLY":
            return RunnerError(
                "PATCH",
                category,
                f"patch apply subprocess timeout after {timeout_s}s ({cmd0})",
            )
        if stage == "PROMOTE":
            return RunnerError(
                "PROMOTION",
                category,
                f"promotion subprocess timeout after {timeout_s}s ({cmd0})",
            )
        if stage == "ARCHIVE":
            return RunnerError(
                "ARCHIVE",
                category,
                f"archive subprocess timeout after {timeout_s}s ({cmd0})",
            )
        if stage in {"PREFLIGHT", "SCOPE", "AUDIT", "SECURITY", "ROLLBACK", "CLEANUP"}:
            return RunnerError(
                stage,
                category,
                f"subprocess timeout after {timeout_s}s ({cmd0})",
            )
        return RunnerError(
            "INTERNAL",
            category,
            f"subprocess timeout after {timeout_s}s during {stage} ({cmd0})",
        )

    def emit_json_hello(
        self, *, issue_id: str | None, mode: str, verbosity: str, log_level: str
    ) -> None:
        with self._io_lock:
            ipc_stream = self._ipc_stream
            need_evt = (self.json_enabled and self._json_fp is not None) or ipc_stream is not None
            if not need_evt:
                return
            self._json_seq += 1
            evt = {
                "type": "hello",
                "protocol": "am_patch_ndjson/1",
                "seq": self._json_seq,
                "ts_mono_ms": self._now_mono_ms(),
                "runner_mode": str(mode or ""),
                "issue_id": issue_id,
                "screen_level": str(verbosity or ""),
                "log_level": str(log_level or ""),
            }
            if self.json_enabled and self._json_fp is not None:
                with contextlib.suppress(Exception):
                    self._write_json(evt)
            if ipc_stream is not None:
                with contextlib.suppress(Exception):
                    ipc_stream(evt)

    def emit_json_result(self, *, summary: TerminalSummary) -> None:
        with self._io_lock:
            ipc_stream = self._ipc_stream
            need_evt = (self.json_enabled and self._json_fp is not None) or ipc_stream is not None
            if not need_evt:
                return
            self._json_seq += 1
            evt = {
                "type": "result",
                "seq": self._json_seq,
                "ts_mono_ms": self._now_mono_ms(),
                "stage": self._get_stage(),
                **result_event_payload(summary),
            }
            if self.json_enabled and self._json_fp is not None:
                with contextlib.suppress(Exception):
                    self._write_json(evt)
            if ipc_stream is not None:
                with contextlib.suppress(Exception):
                    ipc_stream(evt)

    def get_last_json_seq(self) -> int:
        return int(self._json_seq)

    def emit_control_event(
        self,
        payload: dict[str, Any],
        *,
        before_publish: Callable[[int], None] | None = None,
    ) -> int:
        with self._io_lock:
            ipc_stream = self._ipc_stream
            need_evt = (self.json_enabled and self._json_fp is not None) or ipc_stream is not None
            if not need_evt:
                return 0
            self._json_seq += 1
            evt = {
                "seq": self._json_seq,
                "ts_mono_ms": self._now_mono_ms(),
                "stage": self._get_stage(),
                **payload,
            }
            if callable(before_publish):
                with contextlib.suppress(Exception):
                    before_publish(self._json_seq)
            if self.json_enabled and self._json_fp is not None:
                with contextlib.suppress(Exception):
                    self._write_json(evt)
            if ipc_stream is not None:
                with contextlib.suppress(Exception):
                    ipc_stream(evt)
            return self._json_seq

    def _write_machine_event_locked(self, evt: dict[str, Any]) -> tuple[bool, bool]:
        wrote_json = False
        wrote_ipc = False
        if self.json_enabled and self._json_fp is not None:
            try:
                self._write_json(evt)
                wrote_json = True
            except Exception:
                pass
        ipc_stream = self._ipc_stream
        if ipc_stream is not None:
            try:
                ipc_stream(evt)
                wrote_ipc = True
            except Exception:
                pass
        return wrote_json, wrote_ipc

    def emit_json_failed_step_detail(
        self,
        *,
        stdout: str,
        stderr: str,
        severity: Severity,
        channel: Channel,
        bypass: bool,
        include_payload: bool = True,
    ) -> None:
        ipc_stream = self._ipc_stream
        if not ((self.json_enabled and self._json_fp is not None) or ipc_stream is not None):
            return
        with self._io_lock:
            self._json_seq += 1
            evt = {
                "type": "log",
                "seq": self._json_seq,
                "ts_mono_ms": self._now_mono_ms(),
                "stage": self._get_stage(),
                "kind": "TEXT",
                "sev": severity,
                "ch": channel,
                "summary": False,
                "bypass": bool(bypass),
                "msg": "FAILED STEP OUTPUT",
            }
            if include_payload:
                evt["stdout"] = stdout
                evt["stderr"] = stderr
            self._write_machine_event_locked(evt)

    def _write_json_subprocess_stream_locked(
        self, *, stream: str, message: str
    ) -> tuple[bool, bool]:
        kind = {
            "stdout": "SUBPROCESS_STDOUT",
            "stderr": "SUBPROCESS_STDERR",
        }.get(str(stream or "").strip().lower())
        if kind is None:
            raise ValueError(f"unknown subprocess stream: {stream!r}")
        self._json_seq += 1
        evt = {
            "type": "log",
            "seq": self._json_seq,
            "ts_mono_ms": self._now_mono_ms(),
            "stage": self._get_stage(),
            "kind": kind,
            "sev": "DEBUG",
            "ch": "DETAIL",
            "summary": False,
            "bypass": False,
            "msg": _normalize_event_message(message),
        }
        return self._write_machine_event_locked(evt)

    def emit_json_subprocess_stream(self, *, stream: str, message: str) -> None:
        ipc_stream = self._ipc_stream
        if not ((self.json_enabled and self._json_fp is not None) or ipc_stream is not None):
            return
        with self._io_lock:
            self._write_json_subprocess_stream_locked(stream=stream, message=message)

    def _live_subprocess_machine_enabled(self) -> bool:
        return (self.json_enabled and self._json_fp is not None) or self._ipc_stream is not None

    def _live_subprocess_screen_enabled(self) -> bool:
        return _allowed(self.screen_level, "INFO", "DETAIL", summary=False)

    def _live_subprocess_log_enabled(self) -> bool:
        return _allowed(self.log_level, "INFO", "DETAIL", summary=False)

    def _write_live_subprocess_line(
        self,
        *,
        stream: str,
        message: str,
    ) -> tuple[bool, bool, bool]:
        rendered = self._render_live_subprocess_line(stream=stream, message=message)
        wrote_machine = False
        wrote_screen = False
        wrote_log = False
        with self._io_lock:
            if self._live_subprocess_machine_enabled():
                wrote_json, wrote_ipc = self._write_json_subprocess_stream_locked(
                    stream=stream,
                    message=message,
                )
                wrote_machine = wrote_json or wrote_ipc
            if self._live_subprocess_log_enabled():
                self._write_file(rendered)
                wrote_log = True
            if self._live_subprocess_screen_enabled():
                hook = self._screen_break_hook
                if hook is not None:
                    with contextlib.suppress(Exception):
                        hook()
                self._write_screen(rendered)
                wrote_screen = True
        return wrote_machine, wrote_screen, wrote_log

    def _render_live_subprocess_line(self, *, stream: str, message: str) -> str:
        payload = _normalize_event_message(message)
        prefix = f"[{str(stream or '').strip().lower()}]"
        if payload:
            return f"{prefix} {payload}\n"
        return prefix + "\n"

    # Convenience methods
    def debug_detail(self, s: str) -> None:
        self.emit(severity="DEBUG", channel="DETAIL", message=s + "\n")

    def info_core(self, s: str) -> None:
        self.emit(severity="INFO", channel="CORE", message=s + "\n")

    def warning_core(self, s: str) -> None:
        self.emit(severity="WARNING", channel="CORE", message=s + "\n")

    def error_core(self, s: str) -> None:
        self.emit(severity="ERROR", channel="CORE", message=s + "\n")

    def summary(self, s: str) -> None:
        self.emit(severity="INFO", channel="CORE", message=s + "\n", summary=True)

    # Backward-compatible API (DETAIL+INFO)
    def write(self, s: str) -> None:
        self.emit(severity="INFO", channel="DETAIL", message=s)

    def line(self, s: str = "") -> None:
        self.write(s + "\n")

    def section(self, title: str) -> None:
        # Diagnostic section banners must not appear in normal/warning.
        self.emit(severity="INFO", channel="DETAIL", message="\n")
        self.emit(severity="INFO", channel="DETAIL", message=("=" * 80) + "\n")
        self.emit(severity="INFO", channel="DETAIL", message=title + "\n")
        self.emit(severity="INFO", channel="DETAIL", message=("=" * 80) + "\n")

    def emit_error_detail(
        self,
        s: str,
        *,
        to_screen: bool = True,
        to_log: bool = True,
        machine_event: bool = True,
    ) -> None:
        # Full error detail must bypass filtering (visible even in quiet).
        self.emit(
            severity="ERROR",
            channel="CORE",
            message=s,
            error_detail=True,
            to_screen=to_screen,
            to_log=to_log,
            machine_event=machine_event,
        )

    def emit_warning_detail(
        self,
        s: str,
        *,
        to_screen: bool = True,
        to_log: bool = True,
        machine_event: bool = True,
    ) -> None:
        self.emit(
            severity="WARNING",
            channel="DETAIL",
            message=s,
            to_screen=to_screen,
            to_log=to_log,
            machine_event=machine_event,
        )

    def run_logged(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        *,
        failure_dump_mode: str = "bypass",
        timeout_s: int | None = None,
        timeout_hard_fail: bool = True,
        timeout_stage: str | None = None,
        timeout_category: str = "TIMEOUT",
        timeout_message: str | None = None,
    ) -> RunResult:
        # RUN metadata must not appear in normal/warning/verbose; keep it in DETAIL+DEBUG.
        self.emit(severity="DEBUG", channel="DETAIL", kind="RUN", message="RUN\n")
        self.emit(severity="DEBUG", channel="DETAIL", kind="RUN", message=f"cmd={argv}\n")
        if cwd is not None:
            self.emit(severity="DEBUG", channel="DETAIL", kind="RUN", message=f"cwd={str(cwd)}\n")

        timeout_value = self.run_timeout_s if timeout_s is None else int(timeout_s or 0)

        result: RunResult
        screen_got_live = False
        log_got_live = False
        machine_got_live = False

        def _on_live(stream: str, message: str) -> None:
            nonlocal machine_got_live, screen_got_live, log_got_live
            wrote_machine, wrote_screen, wrote_log = self._write_live_subprocess_line(
                stream=stream,
                message=message,
            )
            machine_got_live = machine_got_live or wrote_machine
            screen_got_live = screen_got_live or wrote_screen
            log_got_live = log_got_live or wrote_log

        def _emit_failure_dump(
            emit_line: Callable[..., None],
            *,
            stdout: str,
            stderr: str,
            to_screen: bool,
            to_log: bool,
            machine_event: bool,
            banner: bool,
        ) -> None:
            if not to_screen and not to_log:
                return
            if to_screen:
                hook = self._screen_break_hook
                if hook is not None:
                    with contextlib.suppress(Exception):
                        hook()
            if banner:
                emit_line(
                    "\n" + ("=" * 80) + "\nFAILED STEP OUTPUT\n" + ("=" * 80) + "\n",
                    to_screen=to_screen,
                    to_log=to_log,
                    machine_event=machine_event,
                )
            if stdout:
                emit_line(
                    "[stdout]\n",
                    to_screen=to_screen,
                    to_log=to_log,
                    machine_event=machine_event,
                )
                emit_line(
                    stdout,
                    to_screen=to_screen,
                    to_log=to_log,
                    machine_event=machine_event,
                )
                if not stdout.endswith("\n"):
                    emit_line(
                        "\n",
                        to_screen=to_screen,
                        to_log=to_log,
                        machine_event=machine_event,
                    )
            if stderr:
                emit_line(
                    "[stderr]\n",
                    to_screen=to_screen,
                    to_log=to_log,
                    machine_event=machine_event,
                )
                emit_line(
                    stderr,
                    to_screen=to_screen,
                    to_log=to_log,
                    machine_event=machine_event,
                )
                if not stderr.endswith("\n"):
                    emit_line(
                        "\n",
                        to_screen=to_screen,
                        to_log=to_log,
                        machine_event=machine_event,
                    )

        managed = ManagedSubprocess.start(
            argv=argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout_callback=lambda message: _on_live("stdout", message),
            stderr_callback=lambda message: _on_live("stderr", message),
        )
        self._set_active_subprocess(managed)
        try:
            completed = managed.wait(timeout_s=(timeout_value if timeout_value > 0 else None))
        finally:
            self._set_active_subprocess(None)

        if managed.cancel_requested:
            raise self._cancel_runner_error(argv=argv)

        result = RunResult(
            argv=argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

        dump_screen = not screen_got_live
        dump_log = not log_got_live
        failure_machine_event = not machine_got_live

        if completed.timed_out:
            marker = f"subprocess timeout after {timeout_value}s"
            result.stderr = f"{marker}\n{result.stderr}" if result.stderr else marker + "\n"
            result.returncode = 124
            if timeout_hard_fail:
                self.emit_json_failed_step_detail(
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    severity="ERROR",
                    channel="CORE",
                    bypass=True,
                    include_payload=not machine_got_live,
                )
                _emit_failure_dump(
                    self.emit_error_detail,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    to_screen=dump_screen,
                    to_log=dump_log,
                    machine_event=failure_machine_event,
                    banner=True,
                )
                raise self._timeout_runner_error(
                    timeout_s=timeout_value,
                    timeout_stage=timeout_stage,
                    timeout_category=timeout_category,
                    timeout_message=timeout_message,
                    argv=argv,
                )

        if result.returncode != 0:
            allowed_failure_dump_modes = (
                "bypass",
                "warn_detail",
                "diagnostic_detail",
            )
            if failure_dump_mode not in allowed_failure_dump_modes:
                raise ValueError(f"unknown failure_dump_mode: {failure_dump_mode}")

            if failure_dump_mode == "diagnostic_detail":
                _emit_failure_dump(
                    self.emit_warning_detail,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    to_screen=dump_screen,
                    to_log=dump_log,
                    machine_event=failure_machine_event,
                    banner=False,
                )
                return result

            bypass = failure_dump_mode == "bypass"
            sev: Severity = "ERROR" if bypass else "WARNING"
            ch: Channel = "CORE" if bypass else "DETAIL"
            self.emit_json_failed_step_detail(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                severity=sev,
                channel=ch,
                bypass=bypass,
                include_payload=not machine_got_live,
            )

            emit = self.emit_error_detail if bypass else self.emit_warning_detail
            _emit_failure_dump(
                emit,
                stdout=result.stdout,
                stderr=result.stderr,
                to_screen=dump_screen,
                to_log=dump_log,
                machine_event=failure_machine_event,
                banner=True,
            )

        return result


def new_log_file(
    logs_dir: Path,
    issue_id: str | None,
    *,
    ts_format: str = "%Y%m%d_%H%M%S",
    issue_template: str = "am_patch_issue_{issue}_{ts}.log",
    finalize_template: str = "am_patch_finalize_{ts}.log",
) -> Path:
    ts = time.strftime(ts_format)
    if issue_id:
        name = issue_template.format(issue=issue_id, ts=ts)
    else:
        name = finalize_template.format(ts=ts)
    return logs_dir / name
