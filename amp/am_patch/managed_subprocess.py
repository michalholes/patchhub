from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

_POLL_INTERVAL_S = 0.05
_CANCEL_GRACE_S = 1.0

StreamCallback = Callable[[str], None]


@dataclass(frozen=True)
class CompletedManagedProcess:
    returncode: int
    stdout: str
    stderr: str
    canceled: bool
    timed_out: bool


@dataclass
class ManagedSubprocess:
    process: subprocess.Popen[str]
    stdout_callback: StreamCallback | None = None
    stderr_callback: StreamCallback | None = None
    _stdout_chunks: list[str] = field(default_factory=list)
    _stderr_chunks: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cancel_requested: bool = False
    _stdout_thread: threading.Thread = field(init=False)
    _stderr_thread: threading.Thread = field(init=False)

    def __post_init__(self) -> None:
        self._stdout_thread = threading.Thread(
            target=_drain_stream,
            args=(self.process.stdout, self._stdout_chunks, self.stdout_callback),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=_drain_stream,
            args=(self.process.stderr, self._stderr_chunks, self.stderr_callback),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    @classmethod
    def start(
        cls,
        *,
        argv: list[str],
        cwd: str | None,
        env: dict[str, str] | None,
        stdout_callback: StreamCallback | None = None,
        stderr_callback: StreamCallback | None = None,
    ) -> ManagedSubprocess:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        return cls(
            process=process,
            stdout_callback=stdout_callback,
            stderr_callback=stderr_callback,
        )

    def wait(self, *, timeout_s: int | None = None) -> CompletedManagedProcess:
        deadline = None
        if timeout_s is not None and timeout_s > 0:
            deadline = time.monotonic() + float(timeout_s)

        timed_out = False
        while True:
            try:
                returncode = self.process.wait(timeout=_POLL_INTERVAL_S)
                break
            except subprocess.TimeoutExpired:
                if deadline is None or time.monotonic() < deadline:
                    continue
                timed_out = True
                _terminate_process_tree(self.process)
                returncode = self.process.wait()
                break
        self._stdout_thread.join()
        self._stderr_thread.join()
        return CompletedManagedProcess(
            returncode=returncode,
            stdout="".join(self._stdout_chunks),
            stderr="".join(self._stderr_chunks),
            canceled=self.cancel_requested,
            timed_out=timed_out,
        )

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def request_cancel(self) -> bool:
        with self._lock:
            already_requested = self._cancel_requested
            self._cancel_requested = True
        if already_requested:
            return False
        _terminate_process_tree(self.process)
        return True


def _drain_stream(
    stream: TextIO | None,
    chunks: list[str],
    callback: StreamCallback | None,
) -> None:
    if stream is None:
        return
    try:
        if callback is None:
            _drain_buffered_stream(stream, chunks)
        else:
            _drain_line_stream(stream, chunks, callback)
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def _drain_buffered_stream(stream: TextIO, chunks: list[str]) -> None:
    while True:
        part = stream.read(4096)
        if not part:
            return
        chunks.append(part)


def _drain_line_stream(
    stream: TextIO,
    chunks: list[str],
    callback: StreamCallback,
) -> None:
    while True:
        part = stream.readline()
        if not part:
            return
        chunks.append(part)
        with contextlib.suppress(Exception):
            callback(part)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        _terminate_posix_process_group(process)
        return

    with contextlib.suppress(Exception):
        process.terminate()
    try:
        process.wait(timeout=_CANCEL_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(Exception):
        process.kill()
    with contextlib.suppress(Exception):
        process.wait(timeout=_CANCEL_GRACE_S)


def _terminate_posix_process_group(process: subprocess.Popen[str]) -> None:
    pgid = None
    with contextlib.suppress(Exception):
        pgid = os.getpgid(process.pid)
    if pgid is not None:
        with contextlib.suppress(Exception):
            os.killpg(pgid, signal.SIGTERM)
        if _wait_for_exit(process, grace_s=_CANCEL_GRACE_S):
            return
        with contextlib.suppress(Exception):
            os.killpg(pgid, signal.SIGKILL)
        _wait_for_exit(process, grace_s=_CANCEL_GRACE_S)
        return

    with contextlib.suppress(Exception):
        process.terminate()
    if _wait_for_exit(process, grace_s=_CANCEL_GRACE_S):
        return
    with contextlib.suppress(Exception):
        process.kill()
    _wait_for_exit(process, grace_s=_CANCEL_GRACE_S)


def _wait_for_exit(process: subprocess.Popen[str], *, grace_s: float) -> bool:
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(_POLL_INTERVAL_S)
    return process.poll() is not None
