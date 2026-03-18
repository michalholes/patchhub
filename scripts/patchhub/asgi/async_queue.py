from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from patchhub.models import JobRecord
from patchhub.run_applied_files import collect_job_applied_files
from patchhub.web_jobs_db import WebJobsDatabase

from .async_event_pump import start_event_pump
from .async_events_socket import job_socket_path, send_cancel_async
from .async_runner_exec import AsyncRunnerExecutor, ExecResult
from .async_task_grace import wait_with_grace
from .job_event_broker import JobEventBroker


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_lock_held_sync(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("a+")
    try:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            with contextlib.suppress(Exception):
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        fd.close()


def _drop_override_pairs(argv: list[str], keys: set[str]) -> list[str]:
    out: list[str] = []
    idx = 0
    while idx < len(argv):
        if idx + 1 < len(argv) and argv[idx] == "--override":
            raw = str(argv[idx + 1])
            key = raw.split("=", 1)[0]
            if key in keys:
                idx += 2
                continue
        out.append(argv[idx])
        idx += 1
    return out


def _inject_web_overrides(
    argv: list[str],
    job_id: str,
    *,
    ipc_handshake_wait_s: int,
    db_primary: bool = False,
) -> list[str]:
    drop_keys = {"patch_layout_json_dir", "ipc_socket_path"}
    if db_primary:
        drop_keys.update(
            {
                "json_out",
                "ipc_socket_enabled",
                "ipc_handshake_enabled",
                "ipc_handshake_wait_s",
            }
        )
    out = _drop_override_pairs(list(argv), drop_keys)

    script_idx = -1
    for i, a in enumerate(out):
        if a.endswith("am_patch.py"):
            script_idx = i
            break
    insert_at = script_idx + 1 if script_idx >= 0 else len(out)

    existing = set()
    idx = 0
    while idx + 1 < len(out):
        if out[idx] == "--override":
            existing.add(str(out[idx + 1]).split("=", 1)[0])
            idx += 2
            continue
        idx += 1

    overrides: list[str] = []

    def _add(pair: str) -> None:
        key = pair.split("=", 1)[0]
        if db_primary or key not in existing:
            overrides.extend(["--override", pair])

    if db_primary:
        _add("json_out=false")
    else:
        _add(f"patch_layout_json_dir=artifacts/web_jobs/{job_id}")
    _add("ipc_socket_enabled=true")
    _add("ipc_handshake_enabled=true")
    _add(f"ipc_handshake_wait_s={int(ipc_handshake_wait_s)}")
    _add(f"ipc_socket_path={job_socket_path(job_id)}")
    out[insert_at:insert_at] = overrides
    return out


def _persist_job_sync(job_dir: Path, job: JobRecord) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        json.dumps(job.to_json(), ensure_ascii=True, indent=2), encoding="utf-8"
    )


def _job_jsonl_path_from_fields(job_dir: Path, mode: str, issue_id: str) -> Path:
    if mode in ("finalize_live", "finalize_workspace"):
        return job_dir / "am_patch_finalize.jsonl"
    issue_s = str(issue_id or "")
    if issue_s.isdigit():
        return job_dir / ("am_patch_issue_" + issue_s + ".jsonl")
    return job_dir / "am_patch_finalize.jsonl"


def _ensure_job_jsonl_exists_sync(job_dir: Path, mode: str, issue_id: str) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = _job_jsonl_path_from_fields(job_dir, mode, issue_id)
    line = json.dumps(
        {"type": "log", "ch": "CORE", "sev": "INFO", "msg": "queued", "summary": True},
        ensure_ascii=True,
    )
    jsonl_path.write_text(line + "\n", encoding="utf-8")


_T = TypeVar("_T")


@dataclass
class QueueState:
    queued: int
    running: int


class AsyncJobQueue:
    def __init__(
        self,
        *,
        repo_root: Path,
        lock_path: Path,
        jobs_root: Path,
        executor: AsyncRunnerExecutor,
        ipc_handshake_wait_s: int = 1,
        post_exit_grace_s: int = 5,
        terminate_grace_s: int = 3,
        job_db: WebJobsDatabase | None = None,
        patches_root: Path | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._lock_path = lock_path
        self._jobs_root = jobs_root
        self._executor = executor
        self._ipc_handshake_wait_s = int(ipc_handshake_wait_s)
        self._post_exit_grace_s = max(1, int(post_exit_grace_s))
        self._terminate_grace_s = max(1, int(terminate_grace_s))
        self._job_db = job_db
        self._patches_root = patches_root or jobs_root.parent.parent

        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._mu = asyncio.Lock()
        self._stop = asyncio.Event()
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: dict[str, JobRecord] = {}
        self._task: asyncio.Task[None] | None = None
        self._brokers: dict[str, JobEventBroker] = {}

    def _reset_loop_affine_state(self) -> None:
        self._mu = asyncio.Lock()
        self._stop = asyncio.Event()
        self._q = asyncio.Queue()

    def _set_owner_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        prev = self._owner_loop
        if prev is loop:
            return
        if prev is not None and not prev.is_closed() and self._task is not None:
            raise RuntimeError("AsyncJobQueue owner loop cannot change while running")
        self._owner_loop = loop
        if prev is None or prev.is_closed():
            self._reset_loop_affine_state()

    async def _call_on_owner_loop(self, op: Callable[[], Coroutine[object, object, _T]]) -> _T:
        current = asyncio.get_running_loop()
        owner = self._owner_loop
        if owner is None or owner.is_closed():
            self._set_owner_loop(current)
            return await op()
        if owner is current:
            return await op()
        future: Future[_T] = asyncio.run_coroutine_threadsafe(op(), owner)
        return await asyncio.wrap_future(future)

    async def _pop_broker(self, job_id: str) -> JobEventBroker | None:
        async with self._mu:
            if job_id not in self._brokers:
                return None
            return self._brokers.pop(job_id)

    async def _close_broker(self, job_id: str) -> None:
        broker = await self._pop_broker(job_id)
        if broker is not None:
            broker.close()

    async def _materialize_applied_files(self, job: JobRecord) -> None:
        if self._job_db is None:
            return
        files, source = collect_job_applied_files(
            patches_root=self._patches_root,
            jobs_root=self._jobs_root,
            job=job,
            job_db=self._job_db,
        )
        if files or source != "unavailable":
            job.applied_files = files
            job.applied_files_source = source
            await self._persist(job, count_as_job_change=False)

    async def _finalize_running_job(
        self,
        job_id: str,
        *,
        return_code: int,
        error: str | None,
    ) -> bool:
        finalized: JobRecord | None = None
        async with self._mu:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False
            job.return_code = int(return_code)
            job.error = error
            if int(return_code) == 0:
                job.status = "success"
            elif (
                job.cancel_source == "socket"
                and job.cancel_requested_utc is not None
                and job.cancel_ack_utc is not None
                and int(return_code) == 130
            ) or (
                job.cancel_source in {"terminate", "hard_stop"}
                and job.cancel_requested_utc is not None
                and job.cancel_ack_utc is not None
            ):
                job.status = "canceled"
            else:
                job.status = "fail"
            job.ended_utc = utc_now()
            finalized = job
            await self._persist(job)
        if finalized is not None and finalized.status == "success":
            await self._materialize_applied_files(finalized)
        return True

    async def _reconcile_active_job(
        self,
        job_id: str,
        *,
        return_code: int | None,
        error: str | None,
    ) -> bool:
        async with self._mu:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False

        if await self._executor.is_running():
            return False

        fallback_error = error or "runner_completion_reconciliation_without_return_code"
        fallback_rc = -1 if return_code is None else int(return_code)
        return await self._finalize_running_job(
            job_id, return_code=fallback_rc, error=fallback_error
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._set_owner_loop(asyncio.get_running_loop())
        self._task = asyncio.create_task(self._run_loop(), name="patchhub_async_queue")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(Exception):
                await self._task

    async def _state_local(self) -> QueueState:
        async with self._mu:
            running = sum(1 for j in self._jobs.values() if j.status == "running")
            queued = sum(1 for j in self._jobs.values() if j.status == "queued")
        return QueueState(queued=queued, running=running)

    async def state(self) -> QueueState:
        return await self._call_on_owner_loop(self._state_local)

    async def _list_jobs_local(self) -> list[JobRecord]:
        async with self._mu:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_utc, reverse=True)
        return jobs

    async def list_jobs(self) -> list[JobRecord]:
        return await self._call_on_owner_loop(self._list_jobs_local)

    async def _get_job_local(self, job_id: str) -> JobRecord | None:
        async with self._mu:
            return self._jobs.get(job_id)

    async def get_job(self, job_id: str) -> JobRecord | None:
        return await self._call_on_owner_loop(lambda: self._get_job_local(job_id))

    async def _get_broker_local(self, job_id: str) -> JobEventBroker | None:
        async with self._mu:
            return self._brokers.get(job_id)

    async def get_broker(self, job_id: str) -> JobEventBroker | None:
        return await self._call_on_owner_loop(lambda: self._get_broker_local(job_id))

    async def _enqueue_local(self, job: JobRecord) -> None:
        async with self._mu:
            self._jobs[job.job_id] = job
            await self._persist(job)
            if self._job_db is not None:
                self._job_db.append_event_line(
                    job.job_id,
                    json.dumps(
                        {
                            "type": "log",
                            "ch": "CORE",
                            "sev": "INFO",
                            "msg": "queued",
                            "summary": True,
                        },
                        ensure_ascii=True,
                    ),
                )
            else:
                job_dir = self._job_dir(job.job_id)
                await asyncio.to_thread(
                    _ensure_job_jsonl_exists_sync,
                    job_dir,
                    str(job.mode),
                    str(job.issue_id),
                )
        await self._q.put(job.job_id)

    async def enqueue(self, job: JobRecord) -> None:
        await self._call_on_owner_loop(lambda: self._enqueue_local(job))

    async def _cancel_local(self, job_id: str) -> bool:
        async with self._mu:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            status = str(job.status)

        if status == "queued":
            async with self._mu:
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    return False
                job.status = "canceled"
                job.ended_utc = utc_now()
                await self._persist(job)
            return True

        if status == "running":
            now = utc_now()
            async with self._mu:
                job = self._jobs.get(job_id)
                if job is None:
                    return False
                if job.cancel_requested_utc is None:
                    job.cancel_requested_utc = now
                    await self._persist(job)

            sock_ok = await send_cancel_async(job_socket_path(job_id))
            if sock_ok:
                async with self._mu:
                    job = self._jobs.get(job_id)
                    if job is not None:
                        job.cancel_ack_utc = utc_now()
                        job.cancel_source = "socket"
                        await self._persist(job)
                return True

            ok = await self._executor.terminate(grace_s=self._terminate_grace_s)
            if ok:
                async with self._mu:
                    job = self._jobs.get(job_id)
                    if job is not None:
                        job.cancel_ack_utc = utc_now()
                        job.cancel_source = "terminate"
                        await self._persist(job)
            return ok

        return False

    async def cancel(self, job_id: str) -> bool:
        return await self._call_on_owner_loop(lambda: self._cancel_local(job_id))

    async def _hard_stop_local(self, job_id: str) -> bool:
        async with self._mu:
            job = self._jobs.get(job_id)
            if job is None or str(job.status) != "running":
                return False
            if job.cancel_requested_utc is None:
                job.cancel_requested_utc = utc_now()
                await self._persist(job)

        ok = await self._executor.terminate(grace_s=self._terminate_grace_s)
        if not ok:
            return False

        async with self._mu:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.cancel_ack_utc = utc_now()
            job.cancel_source = "hard_stop"
            await self._persist(job)
        return True

    async def hard_stop(self, job_id: str) -> bool:
        return await self._call_on_owner_loop(lambda: self._hard_stop_local(job_id))

    def jobs_root(self) -> Path:
        return self._jobs_root

    def _job_dir(self, job_id: str) -> Path:
        return self._jobs_root / job_id

    async def _persist(self, job: JobRecord, *, count_as_job_change: bool = True) -> None:
        if self._job_db is not None:
            await asyncio.to_thread(
                self._job_db.upsert_job, job, count_as_job_change=count_as_job_change
            )
            return
        job_dir = self._job_dir(job.job_id)
        await asyncio.to_thread(_persist_job_sync, job_dir, job)

    async def _wait_for_runner_slot(self) -> None:
        while True:
            if self._stop.is_set():
                return
            if await self._executor.is_running():
                await asyncio.sleep(0.25)
                continue

            held = await asyncio.to_thread(is_lock_held_sync, self._lock_path)
            if not held:
                return
            await asyncio.sleep(0.25)

    def _compose_tail_timeout_error(
        self,
        job: JobRecord,
        *,
        res: ExecResult,
        pump_tail_timed_out: bool,
    ) -> str | None:
        reasons: list[str] = []
        if res.stdout_tail_timed_out:
            reasons.append("stdout_tail_timeout_after_runner_exit")
        if pump_tail_timed_out:
            reasons.append("event_pump_tail_timeout_after_runner_exit")
        if not reasons:
            return job.error
        if job.error:
            reasons.insert(0, str(job.error))
        return "; ".join(reasons)

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            job_id = await self._q.get()
            result: ExecResult | None = None
            pump_tail_timed_out = False

            async with self._mu:
                job = self._jobs.get(job_id)
                if job is None:
                    continue

            await self._wait_for_runner_slot()
            if self._stop.is_set():
                return

            async with self._mu:
                job = self._jobs.get(job_id)
                if job is None:
                    continue
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started_utc = utc_now()
                await self._persist(job)

            job_dir = self._job_dir(job_id)
            runner_log = job_dir / "runner.log"
            jsonl_path = _job_jsonl_path_from_fields(job_dir, str(job.mode), str(job.issue_id))

            try:
                effective_cmd = _inject_web_overrides(
                    job.canonical_command,
                    job_id,
                    ipc_handshake_wait_s=self._ipc_handshake_wait_s,
                    db_primary=self._job_db is not None,
                )

                sock_path = Path(job_socket_path(job_id))
                sock_path.parent.mkdir(parents=True, exist_ok=True)
                if sock_path.exists() or sock_path.is_symlink():
                    with contextlib.suppress(Exception):
                        sock_path.unlink()

                broker = JobEventBroker()
                async with self._mu:
                    self._brokers[job_id] = broker
                if self._job_db is not None:
                    pump_coro = start_event_pump(
                        socket_path=str(sock_path),
                        jsonl_path=None,
                        publish=broker.publish,
                        job_db=self._job_db,
                        job_id=job_id,
                    )
                else:
                    pump_coro = start_event_pump(
                        socket_path=str(sock_path),
                        jsonl_path=jsonl_path,
                        publish=broker.publish,
                    )
                pump_task = asyncio.create_task(
                    pump_coro,
                    name=f"patchhub_event_pump_{job_id}",
                )

                if self._job_db is not None:
                    result = await self._executor.run(
                        effective_cmd,
                        cwd=self._repo_root,
                        log_path=None,
                        job_db=self._job_db,
                        job_id=job_id,
                        post_exit_grace_s=self._post_exit_grace_s,
                    )
                else:
                    result = await self._executor.run(
                        effective_cmd,
                        cwd=self._repo_root,
                        log_path=runner_log,
                        post_exit_grace_s=self._post_exit_grace_s,
                    )

                pump_tail_timed_out = await wait_with_grace(
                    pump_task, grace_s=self._post_exit_grace_s
                )

                async with self._mu:
                    job = self._jobs.get(job_id)
                    if job is None:
                        continue
                    error = self._compose_tail_timeout_error(
                        job,
                        res=result,
                        pump_tail_timed_out=pump_tail_timed_out,
                    )

                await self._finalize_running_job(
                    job_id, return_code=result.return_code, error=error
                )
            except Exception as e:
                if result is not None:
                    async with self._mu:
                        job = self._jobs.get(job_id)
                        if job is not None:
                            if job.error:
                                job.error = f"{job.error}; {type(e).__name__}: {e}"
                            else:
                                job.error = f"{type(e).__name__}: {e}"
                    continue

                async with self._mu:
                    job = self._jobs.get(job_id)
                    if job is None:
                        continue
                    job.status = "fail" if job.status != "canceled" else job.status
                    job.ended_utc = utc_now()
                    job.error = f"{type(e).__name__}: {e}"
                    await self._persist(job)
            finally:
                reconcile_error: str | None = None
                reconcile_return_code: int | None = None
                if result is not None:
                    reconcile_return_code = result.return_code
                    async with self._mu:
                        current_job = self._jobs.get(job_id)
                    if current_job is not None:
                        reconcile_error = self._compose_tail_timeout_error(
                            current_job,
                            res=result,
                            pump_tail_timed_out=pump_tail_timed_out,
                        )

                await self._reconcile_active_job(
                    job_id,
                    return_code=reconcile_return_code,
                    error=reconcile_error,
                )
                await self._close_broker(job_id)
                with contextlib.suppress(Exception):
                    Path(job_socket_path(job_id)).unlink()
