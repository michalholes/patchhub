# ruff: noqa: E402
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import patchhub.asgi.async_event_pump as async_event_pump_mod
import patchhub.asgi.async_queue as async_queue_mod
from patchhub.models import JobRecord


class _FakeExecutor:
    async def is_running(self) -> bool:
        return False

    async def terminate(self, *, grace_s: int = 3) -> bool:
        del grace_s
        return False

    async def run(
        self,
        argv: list[str],
        cwd: Path,
        log_path: Path,
        *,
        post_exit_grace_s: int = 5,
    ):
        del argv, cwd, post_exit_grace_s
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("runner\n", encoding="utf-8")
        return type(
            "ExecResult",
            (),
            {"return_code": 0, "stdout_tail_timed_out": False},
        )()


async def _fast_wait_with_grace(
    task: asyncio.Task[object],
    *,
    grace_s: int,
) -> bool:
    del grace_s
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=0.02)
        return False
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True


_ORIGINAL_COMMAND_SEND = async_event_pump_mod.EventPumpCommandChannel.send


async def _fast_command_send(self, **kwargs) -> bool:
    kwargs["timeout_s"] = 0.05
    return await _ORIGINAL_COMMAND_SEND(self, **kwargs)


class _FakeFailingFinalizeQueue(async_queue_mod.AsyncJobQueue):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.finalize_attempts = 0

    async def _finalize_running_job(
        self,
        job_id: str,
        *,
        return_code: int,
        error: str | None,
    ) -> bool:
        self.finalize_attempts += 1
        if self.finalize_attempts == 1:
            raise RuntimeError("injected finalize failure")
        return await super()._finalize_running_job(
            job_id,
            return_code=return_code,
            error=error,
        )


class TestPatchhubAsyncQueueCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_runner_completion_waits_for_pump_tail_before_finalizing(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            jobs_root = root / "jobs"
            repo_root.mkdir()
            jobs_root.mkdir()
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
                post_exit_grace_s=1,
            )
            job = JobRecord(
                job_id="job-504-tail",
                created_utc="2026-03-06T00:00:00Z",
                mode="patch",
                issue_id="504",
                commit_summary="Fix PatchHub completion sequencing",
                patch_basename="issue_504.zip",
                raw_command=(
                    "python3 scripts/am_patch.py 504 "
                    '"Fix PatchHub completion sequencing" '
                    "patches/issue_504.zip"
                ),
                canonical_command=["python3", "scripts/am_patch.py", "504"],
            )

            async def fake_start_event_pump(
                *,
                socket_path: str,
                jsonl_path: Path,
                publish=None,
                command_channel=None,
                connect_timeout_s: float = 10.0,
                retry_sleep_s: float = 0.25,
            ) -> None:
                del socket_path, command_channel, connect_timeout_s, retry_sleep_s
                await asyncio.sleep(0.02)
                line = '{"type":"log","msg":"tail"}'
                with jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    end_offset = f.tell()
                if publish is not None:
                    publish(line, end_offset)

            async def wait_for_success() -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 2.0
                while True:
                    current = await queue.get_job(job.job_id)
                    if current is not None and current.status == "success":
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError("job did not finish")
                    await asyncio.sleep(0.01)

            with (
                patch.object(
                    async_queue_mod,
                    "start_event_pump",
                    side_effect=fake_start_event_pump,
                ),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    return_value=str(root / "job-504-tail.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    finished = await wait_for_success()
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.return_code, 0)
            jsonl_path = jobs_root / job.job_id / "am_patch_issue_504.jsonl"
            jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(jsonl_lines[-1], '{"type":"log","msg":"tail"}')
            job_json = json.loads((jobs_root / job.job_id / "job.json").read_text())
            self.assertEqual(job_json["status"], "success")


class TestPatchhubAsyncQueueForcedCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_event_pump_timeout_finalizes_job_and_unblocks_queue(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
                post_exit_grace_s=1,
            )
            first = JobRecord(
                job_id="job-601-first",
                created_utc="2026-03-06T00:00:00Z",
                mode="patch",
                issue_id="601",
                commit_summary="First",
                patch_basename="issue_601.zip",
                raw_command="python3 scripts/am_patch.py 601",
                canonical_command=["python3", "scripts/am_patch.py", "601"],
            )
            second = JobRecord(
                job_id="job-601-second",
                created_utc="2026-03-06T00:00:01Z",
                mode="patch",
                issue_id="602",
                commit_summary="Second",
                patch_basename="issue_602.zip",
                raw_command="python3 scripts/am_patch.py 602",
                canonical_command=["python3", "scripts/am_patch.py", "602"],
            )

            async def hanging_pump(
                *,
                socket_path: str,
                jsonl_path: Path,
                publish=None,
                command_channel=None,
                connect_timeout_s: float = 10.0,
                retry_sleep_s: float = 0.25,
            ) -> None:
                del (
                    socket_path,
                    jsonl_path,
                    publish,
                    command_channel,
                    connect_timeout_s,
                    retry_sleep_s,
                )
                await asyncio.sleep(3600)

            async def wait_for_done(job_id: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job_id)
                    if current is not None and current.status in {
                        "success",
                        "fail",
                        "canceled",
                    }:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job_id} did not finish")
                    await asyncio.sleep(0.01)

            with (
                patch.object(
                    async_queue_mod,
                    "start_event_pump",
                    side_effect=hanging_pump,
                ),
                patch.object(
                    async_queue_mod,
                    "wait_with_grace",
                    side_effect=_fast_wait_with_grace,
                ),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    side_effect=lambda job_id: str(root / f"{job_id}.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(first)
                    await queue.enqueue(second)
                    finished_first = await wait_for_done(first.job_id)
                    finished_second = await wait_for_done(second.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished_first.status, "success")
            self.assertEqual(finished_second.status, "success")
            self.assertEqual(
                finished_first.error,
                "event_pump_tail_timeout_after_runner_exit",
            )

    async def test_reconciliation_finalizes_running_job_after_finalize_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = _FakeFailingFinalizeQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
                post_exit_grace_s=1,
            )
            job = JobRecord(
                job_id="job-603-reconcile",
                created_utc="2026-03-06T00:00:00Z",
                mode="patch",
                issue_id="603",
                commit_summary="Reconcile",
                patch_basename="issue_603.zip",
                raw_command="python3 scripts/am_patch.py 603",
                canonical_command=["python3", "scripts/am_patch.py", "603"],
            )

            async def hanging_pump(
                *,
                socket_path: str,
                jsonl_path: Path,
                publish=None,
                command_channel=None,
                connect_timeout_s: float = 10.0,
                retry_sleep_s: float = 0.25,
            ) -> None:
                del (
                    socket_path,
                    jsonl_path,
                    publish,
                    command_channel,
                    connect_timeout_s,
                    retry_sleep_s,
                )
                await asyncio.sleep(3600)

            async def wait_for_done(job_id: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job_id)
                    if current is not None and current.status in {
                        "success",
                        "fail",
                        "canceled",
                    }:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job_id} did not finish")
                    await asyncio.sleep(0.01)

            with (
                patch.object(
                    async_queue_mod,
                    "start_event_pump",
                    side_effect=hanging_pump,
                ),
                patch.object(
                    async_queue_mod,
                    "wait_with_grace",
                    side_effect=_fast_wait_with_grace,
                ),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    side_effect=lambda job_id: str(root / f"{job_id}.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    finished = await wait_for_done(job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(queue.finalize_attempts, 2)
            self.assertEqual(finished.status, "success")
            self.assertIn("RuntimeError: injected finalize failure", finished.error)
            self.assertIn(
                "event_pump_tail_timeout_after_runner_exit",
                finished.error,
            )

    async def test_forced_completion_persists_status_before_broker_close(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
                post_exit_grace_s=1,
            )
            job = JobRecord(
                job_id="job-604-ordering",
                created_utc="2026-03-06T00:00:00Z",
                mode="patch",
                issue_id="604",
                commit_summary="Ordering",
                patch_basename="issue_604.zip",
                raw_command="python3 scripts/am_patch.py 604",
                canonical_command=["python3", "scripts/am_patch.py", "604"],
            )
            persisted_statuses: list[str] = []
            original_close = async_queue_mod.JobEventBroker.close

            async def hanging_pump(
                *,
                socket_path: str,
                jsonl_path: Path,
                publish=None,
                command_channel=None,
                connect_timeout_s: float = 10.0,
                retry_sleep_s: float = 0.25,
            ) -> None:
                del (
                    socket_path,
                    jsonl_path,
                    publish,
                    command_channel,
                    connect_timeout_s,
                    retry_sleep_s,
                )
                await asyncio.sleep(3600)

            def recording_close(broker: async_queue_mod.JobEventBroker) -> None:
                job_json = jobs_root / job.job_id / "job.json"
                persisted_statuses.append(
                    json.loads(job_json.read_text(encoding="utf-8"))["status"]
                )
                original_close(broker)

            async def wait_for_done(job_id: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job_id)
                    if current is not None and current.status in {
                        "success",
                        "fail",
                        "canceled",
                    }:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job_id} did not finish")
                    await asyncio.sleep(0.01)

            with (
                patch.object(
                    async_queue_mod,
                    "start_event_pump",
                    side_effect=hanging_pump,
                ),
                patch.object(
                    async_queue_mod,
                    "wait_with_grace",
                    side_effect=_fast_wait_with_grace,
                ),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    side_effect=lambda job_id: str(root / f"{job_id}.sock"),
                ),
                patch.object(async_queue_mod.JobEventBroker, "close", new=recording_close),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    finished = await wait_for_done(job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.status, "success")
            self.assertEqual(persisted_statuses, ["success"])


class _ControllableExecutor:
    def __init__(self, *, return_code: int) -> None:
        self.return_code = int(return_code)
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.running = False
        self.terminate_calls: list[int] = []

    async def is_running(self) -> bool:
        return self.running

    async def terminate(self, *, grace_s: int = 3) -> bool:
        self.terminate_calls.append(int(grace_s))
        self.released.set()
        return True

    async def run(
        self,
        argv: list[str],
        cwd: Path,
        log_path: Path,
        *,
        post_exit_grace_s: int = 5,
    ):
        del argv, cwd, post_exit_grace_s
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("runner\n", encoding="utf-8")
        self.running = True
        self.started.set()
        await self.released.wait()
        self.running = False
        return async_queue_mod.ExecResult(return_code=self.return_code, stdout_tail_timed_out=False)


class _CommandPumpWriter:
    def __init__(self) -> None:
        self.lines: asyncio.Queue[bytes] = asyncio.Queue()
        self._closing = False

    def write(self, data: bytes) -> None:
        self.lines.put_nowait(data)

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True


class TestPatchhubAsyncQueueCancelStates(unittest.IsolatedAsyncioTestCase):
    async def test_socket_cancel_exit_code_130_finalizes_as_canceled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            executor = _ControllableExecutor(return_code=130)
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=executor,
                post_exit_grace_s=1,
                terminate_grace_s=3,
            )
            job = JobRecord(
                job_id="job-650-socket-cancel",
                created_utc="2026-03-07T00:00:00Z",
                mode="patch",
                issue_id="650",
                commit_summary="Socket cancel",
                patch_basename="issue_650.zip",
                raw_command="python3 scripts/am_patch.py 650",
                canonical_command=["python3", "scripts/am_patch.py", "650"],
            )
            cancel_seen = asyncio.Event()
            writer = _CommandPumpWriter()

            async def command_pump(**kwargs):
                command_channel = kwargs["command_channel"]
                await command_channel.attach_writer(writer)
                try:
                    while True:
                        raw = await writer.lines.get()
                        obj = json.loads(raw.decode("utf-8"))
                        if str(obj.get("cmd", "")) != "cancel":
                            continue
                        cancel_seen.set()
                        command_channel.deliver_reply(
                            {
                                "type": "reply",
                                "cmd": "cancel",
                                "cmd_id": str(obj["cmd_id"]),
                                "ok": True,
                            }
                        )
                        return None
                finally:
                    writer.close()
                    await command_channel.close()

            async def wait_for_status(expected: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job.job_id)
                    if current is not None and current.status == expected:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job.job_id} did not reach {expected}")
                    await asyncio.sleep(0.01)

            with (
                patch.object(async_queue_mod, "start_event_pump", side_effect=command_pump),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    return_value=str(root / "job-650.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    await asyncio.wait_for(executor.started.wait(), timeout=1.0)
                    self.assertTrue(await queue.cancel(job.job_id))
                    await asyncio.wait_for(cancel_seen.wait(), timeout=1.0)
                    executor.released.set()
                    finished = await wait_for_status("canceled")
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.return_code, 130)
            self.assertEqual(finished.cancel_source, "socket")
            self.assertIsNotNone(finished.cancel_ack_utc)
            self.assertEqual(executor.terminate_calls, [])

    async def test_cancel_fallback_terminate_finalizes_as_canceled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            executor = _ControllableExecutor(return_code=-15)
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=executor,
                post_exit_grace_s=1,
                terminate_grace_s=4,
            )
            job = JobRecord(
                job_id="job-651-terminate-cancel",
                created_utc="2026-03-07T00:00:00Z",
                mode="patch",
                issue_id="651",
                commit_summary="Terminate cancel",
                patch_basename="issue_651.zip",
                raw_command="python3 scripts/am_patch.py 651",
                canonical_command=["python3", "scripts/am_patch.py", "651"],
            )
            cancel_seen = asyncio.Event()
            writer = _CommandPumpWriter()

            async def timeout_command_pump(**kwargs):
                command_channel = kwargs["command_channel"]
                await command_channel.attach_writer(writer)
                try:
                    while True:
                        raw = await writer.lines.get()
                        obj = json.loads(raw.decode("utf-8"))
                        if str(obj.get("cmd", "")) != "cancel":
                            continue
                        cancel_seen.set()
                        await asyncio.sleep(0.1)
                        return None
                finally:
                    writer.close()
                    await command_channel.close()

            async def wait_for_status(expected: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 6.0
                while True:
                    current = await queue.get_job(job.job_id)
                    if current is not None and current.status == expected:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job.job_id} did not reach {expected}")
                    await asyncio.sleep(0.01)

            with (
                patch.object(
                    async_queue_mod,
                    "start_event_pump",
                    side_effect=timeout_command_pump,
                ),
                patch.object(
                    async_event_pump_mod.EventPumpCommandChannel,
                    "send",
                    new=_fast_command_send,
                ),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    return_value=str(root / "job-651.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    await asyncio.wait_for(executor.started.wait(), timeout=1.0)
                    self.assertTrue(await queue.cancel(job.job_id))
                    await asyncio.wait_for(cancel_seen.wait(), timeout=1.0)
                    finished = await wait_for_status("canceled")
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.cancel_source, "terminate")
            self.assertIsNotNone(finished.cancel_ack_utc)
            self.assertEqual(executor.terminate_calls, [4])

    async def test_successful_runner_fails_when_end_head_capture_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
                target_repo_roots={"patchhub": repo_root},
            )
            job = JobRecord(
                job_id="job-380-end-capture-fail",
                created_utc="2026-03-24T10:00:00Z",
                mode="patch",
                issue_id="380",
                commit_summary="Capture fail",
                patch_basename="issue_380_v1.zip",
                raw_command="python3 scripts/am_patch.py 380",
                canonical_command=["python3", "scripts/am_patch.py", "380"],
                effective_runner_target_repo="patchhub",
            )

            capture_calls = 0

            def fake_capture(_repo_root: Path) -> str:
                nonlocal capture_calls
                capture_calls += 1
                if capture_calls == 1:
                    return "start-sha"
                raise async_queue_mod.RevertJobRuntimeError("cannot capture final HEAD")

            async def idle_pump(**kwargs):
                del kwargs
                return None

            async def wait_for_status(expected: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job.job_id)
                    if current is not None and current.status == expected:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job.job_id} did not reach {expected}")
                    await asyncio.sleep(0.01)

            with (
                patch.object(async_queue_mod, "capture_head_sha", side_effect=fake_capture),
                patch.object(async_queue_mod, "start_event_pump", side_effect=idle_pump),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    return_value=str(root / "job-380.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    finished = await wait_for_status("fail")
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.run_start_sha, "start-sha")
            self.assertIsNone(finished.run_end_sha)
            self.assertIn("cannot capture final HEAD", str(finished.error or ""))

    async def test_hard_stop_running_job_finalizes_as_canceled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            executor = _ControllableExecutor(return_code=-9)
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=executor,
                post_exit_grace_s=1,
                terminate_grace_s=5,
            )
            job = JobRecord(
                job_id="job-652-hard-stop",
                created_utc="2026-03-07T00:00:00Z",
                mode="patch",
                issue_id="652",
                commit_summary="Hard stop",
                patch_basename="issue_652.zip",
                raw_command="python3 scripts/am_patch.py 652",
                canonical_command=["python3", "scripts/am_patch.py", "652"],
            )

            async def idle_pump(**kwargs):
                del kwargs
                return None

            async def wait_for_status(expected: str) -> async_queue_mod.JobRecord:
                deadline = asyncio.get_running_loop().time() + 3.0
                while True:
                    current = await queue.get_job(job.job_id)
                    if current is not None and current.status == expected:
                        return current
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(f"{job.job_id} did not reach {expected}")
                    await asyncio.sleep(0.01)

            with (
                patch.object(async_queue_mod, "start_event_pump", side_effect=idle_pump),
                patch.object(
                    async_queue_mod,
                    "job_socket_path",
                    return_value=str(root / "job-652.sock"),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    await asyncio.wait_for(executor.started.wait(), timeout=1.0)
                    self.assertTrue(await queue.hard_stop(job.job_id))
                    finished = await wait_for_status("canceled")
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.cancel_source, "hard_stop")
            self.assertIsNotNone(finished.cancel_ack_utc)
            self.assertEqual(executor.terminate_calls, [5])


class TestPatchhubAsyncQueueCleanupHook(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_cleanup_runs_for_success_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
            )
            calls: list[tuple[str, str]] = []

            async def _on_patch_success(job: JobRecord) -> None:
                calls.append((job.job_id, job.mode))

            queue.set_patch_success_callback(_on_patch_success)
            job = JobRecord(
                job_id="job-375-success",
                created_utc="2026-03-23T10:00:00Z",
                mode="patch",
                issue_id="375",
                commit_summary="Cleanup",
                patch_basename="issue_375_v1.zip",
                raw_command="python3 scripts/am_patch.py 375",
                canonical_command=["python3", "scripts/am_patch.py", "375"],
                status="running",
            )
            queue._jobs[job.job_id] = job

            changed = await queue._finalize_running_job(
                job.job_id,
                return_code=0,
                error=None,
            )

            self.assertTrue(changed)
            self.assertEqual(queue._jobs[job.job_id].status, "success")
            self.assertEqual(calls, [(job.job_id, "patch")])

    async def test_patch_success_callback_failure_is_persisted_without_reclassifying(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
            )

            async def _on_patch_success(job: JobRecord) -> None:
                raise RuntimeError("cleanup callback boom")

            queue.set_patch_success_callback(_on_patch_success)
            job = JobRecord(
                job_id="job-375-callback-fail",
                created_utc="2026-03-23T10:00:00Z",
                mode="patch",
                issue_id="375",
                commit_summary="Cleanup",
                patch_basename="issue_375_v1.zip",
                raw_command="python3 scripts/am_patch.py 375",
                canonical_command=["python3", "scripts/am_patch.py", "375"],
                status="running",
            )
            queue._jobs[job.job_id] = job

            changed = await queue._finalize_running_job(
                job.job_id,
                return_code=0,
                error=None,
            )

            persisted = await queue.get_job(job.job_id)
            self.assertTrue(changed)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.status, "success")
            self.assertEqual(
                persisted.error,
                "RuntimeError: cleanup callback boom",
            )

    async def test_terminal_cleanup_runs_for_non_patch_and_failed_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
            )
            calls: list[str] = []

            async def _on_patch_success(job: JobRecord) -> None:
                calls.append(job.job_id)

            queue.set_patch_success_callback(_on_patch_success)
            repair_job = JobRecord(
                job_id="job-375-repair",
                created_utc="2026-03-23T10:00:01Z",
                mode="repair",
                issue_id="375",
                commit_summary="Repair",
                patch_basename="issue_375_v1.zip",
                raw_command="python3 scripts/am_patch.py 375",
                canonical_command=["python3", "scripts/am_patch.py", "375"],
                status="running",
            )
            fail_job = JobRecord(
                job_id="job-375-fail",
                created_utc="2026-03-23T10:00:02Z",
                mode="patch",
                issue_id="375",
                commit_summary="Fail",
                patch_basename="issue_375_v1.zip",
                raw_command="python3 scripts/am_patch.py 375",
                canonical_command=["python3", "scripts/am_patch.py", "375"],
                status="running",
            )
            queue._jobs[repair_job.job_id] = repair_job
            queue._jobs[fail_job.job_id] = fail_job

            await queue._finalize_running_job(
                repair_job.job_id,
                return_code=0,
                error=None,
            )
            await queue._finalize_running_job(
                fail_job.job_id,
                return_code=1,
                error="boom",
            )

            self.assertEqual(queue._jobs[repair_job.job_id].status, "success")
            self.assertEqual(queue._jobs[fail_job.job_id].status, "fail")
            self.assertEqual(calls, ["job-375-repair", "job-375-fail"])

    async def test_terminal_cleanup_runs_for_queued_cancel(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_FakeExecutor(),
            )
            calls: list[str] = []

            async def _on_patch_success(job: JobRecord) -> None:
                calls.append(f"{job.job_id}:{job.status}")

            queue.set_patch_success_callback(_on_patch_success)
            queued_job = JobRecord(
                job_id="job-375-queued-cancel",
                created_utc="2026-03-23T10:00:03Z",
                mode="patch",
                issue_id="375",
                commit_summary="Queued cancel",
                patch_basename="issue_375_v1.zip",
                raw_command="python3 scripts/am_patch.py 375",
                canonical_command=["python3", "scripts/am_patch.py", "375"],
                status="queued",
            )
            queue._jobs[queued_job.job_id] = queued_job

            changed = await queue._cancel_local(queued_job.job_id)

            self.assertTrue(changed)
            self.assertEqual(queue._jobs[queued_job.job_id].status, "canceled")
            self.assertEqual(calls, ["job-375-queued-cancel:canceled"])
