from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class StatusState:
    stage: str = "PREFLIGHT"
    started: float = 0.0


class StatusReporter:
    """Best-effort progress indicator.

    - In TTY: updates a single line on stderr using carriage return.
    - In non-TTY: prints periodic heartbeat lines to stderr.
    - Intended to be silent when disabled (e.g. verbosity=quiet).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        interval_tty: float = 1.0,
        interval_non_tty: float = 1.0,
    ) -> None:
        self._enabled = enabled
        self._interval_tty = interval_tty
        self._interval_non_tty = interval_non_tty
        self._state = StatusState(stage="PREFLIGHT", started=time.monotonic())
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tty_line_open = False
        self._tty_last_len = 0
        self._heartbeat_hook: Callable[[], None] | None = None

    def start(self) -> None:
        if not self._enabled:
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="am_patch_status", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        self._thread = None
        if sys.stderr.isatty():
            # End any active status line.
            self._tty_line_open = False
            self._tty_last_len = 0
            sys.stderr.write("\r\n")
            sys.stderr.flush()

    def set_stage(self, stage: str) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._state.stage = stage

    def get_stage(self) -> str:
        with self._lock:
            return self._state.stage

    def set_heartbeat_hook(self, hook: Callable[[], None] | None) -> None:
        with self._lock:
            self._heartbeat_hook = hook

    def break_line(self) -> None:
        """Terminate an active TTY status line with a newline.

        This prevents subsequent normal output lines (typically on stdout)
        from visually appending to the in-place status line.
        """
        if not self._enabled:
            return
        if not sys.stderr.isatty():
            return
        with self._lock:
            if not self._tty_line_open:
                return
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._tty_line_open = False

    def _elapsed_mmss(self) -> str:
        with self._lock:
            started = self._state.started
        elapsed = max(0.0, time.monotonic() - started)
        mm = int(elapsed // 60)
        ss = int(elapsed % 60)
        return f"{mm:02d}:{ss:02d}"

    def _render_tty(self) -> None:
        with self._lock:
            stage = self._state.stage
            last_len = self._tty_last_len
        msg = f"STATUS: {stage}  ELAPSED: {self._elapsed_mmss()}"
        pad = max(0, last_len - len(msg))
        sys.stderr.write("\r" + msg + (" " * pad))
        sys.stderr.flush()
        with self._lock:
            self._tty_line_open = True
            self._tty_last_len = max(self._tty_last_len, len(msg))

    def _render_non_tty(self) -> None:
        with self._lock:
            stage = self._state.stage
        sys.stderr.write(f"HEARTBEAT: {stage} elapsed={self._elapsed_mmss()}\n")
        sys.stderr.flush()

    def _emit_heartbeat_hook(self) -> None:
        with self._lock:
            hook = self._heartbeat_hook
        if hook is None:
            return
        try:
            hook()
        except Exception:
            return

    def _run(self) -> None:
        is_tty = sys.stderr.isatty()
        interval = self._interval_tty if is_tty else self._interval_non_tty
        # First tick quickly so user sees it.
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_tick:
                if is_tty:
                    self._render_tty()
                else:
                    self._render_non_tty()
                self._emit_heartbeat_hook()
                next_tick = now + interval
            self._stop.wait(0.2)
