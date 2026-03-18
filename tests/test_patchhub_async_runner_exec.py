# ruff: noqa: E402
from __future__ import annotations

import asyncio
import signal
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_runner_exec import AsyncRunnerExecutor


class _EmptyStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(3600)
        return b""


class _HangingStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(3600)
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _HangingStdout()
        self.returncode: int | None = None
        self.pid = 1234

    async def wait(self) -> int:
        self.returncode = 0
        return 0


class _TerminatingProcess:
    def __init__(self) -> None:
        self.stdout = _EmptyStdout()
        self.returncode: int | None = None
        self.pid = 4321
        self._killed = False

    async def wait(self) -> int:
        if self._killed:
            self.returncode = -9
            return -9
        await asyncio.sleep(3600)
        return -9


class TestPatchhubAsyncRunnerExec(unittest.IsolatedAsyncioTestCase):
    async def test_run_times_out_hanging_stdout_tail_after_exit(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "runner.log"
            proc = _FakeProcess()
            executor = AsyncRunnerExecutor()
            with patch(
                "patchhub.asgi.async_runner_exec.asyncio.create_subprocess_exec",
                return_value=proc,
            ):
                result = await executor.run(
                    ["python3", "scripts/am_patch.py", "500"],
                    cwd=root,
                    log_path=log_path,
                    post_exit_grace_s=1,
                )

            self.assertEqual(result.return_code, 0)
            self.assertTrue(result.stdout_tail_timed_out)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")

    async def test_run_starts_runner_in_new_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "runner.log"
            proc = _FakeProcess()
            seen: dict[str, object] = {}

            async def fake_create(*argv: str, **kwargs: object) -> _FakeProcess:
                seen["argv"] = argv
                seen["kwargs"] = kwargs
                return proc

            executor = AsyncRunnerExecutor()
            with patch(
                "patchhub.asgi.async_runner_exec.asyncio.create_subprocess_exec",
                side_effect=fake_create,
            ):
                await executor.run(
                    ["python3", "scripts/am_patch.py", "500"],
                    cwd=root,
                    log_path=log_path,
                    post_exit_grace_s=1,
                )

        self.assertEqual(seen["argv"], ("python3", "scripts/am_patch.py", "500"))
        kwargs = seen["kwargs"]
        assert isinstance(kwargs, dict)
        self.assertIs(kwargs["start_new_session"], True)

    async def test_terminate_escalates_from_term_to_kill_for_runner_group(self) -> None:
        proc = _TerminatingProcess()
        executor = AsyncRunnerExecutor()
        async with executor._lock:
            executor._proc = proc

        signals: list[tuple[int, int]] = []

        def fake_killpg(pid: int, sig: int) -> None:
            signals.append((pid, sig))
            if sig == signal.SIGKILL:
                proc._killed = True

        with patch("patchhub.asgi.async_runner_exec.os.killpg", side_effect=fake_killpg):
            ok = await executor.terminate(grace_s=1)

        self.assertTrue(ok)
        self.assertEqual(signals, [(4321, signal.SIGTERM), (4321, signal.SIGKILL)])
