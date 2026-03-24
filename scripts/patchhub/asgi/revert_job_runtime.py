from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase
from patchhub.web_jobs_legacy_fs import load_legacy_job_record


class RevertJobRuntimeError(RuntimeError):
    pass


class EventBroker(Protocol):
    def publish(self, raw: str, end_offset: int) -> None: ...


@dataclass(frozen=True)
class GitCommandResult:
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class GitAbortResult:
    attempted: bool
    result: GitCommandResult | None


@dataclass(frozen=True)
class RevertFailureVerification:
    actual_head: str | None
    error: str | None


class RevertJobHandler:
    def __init__(
        self,
        *,
        load_job_record_any: Callable[[str], Awaitable[JobRecord | None]],
        resolve_target_root: Callable[[JobRecord], Path],
        capture_head_sha_for_job: Callable[[JobRecord], Awaitable[str]],
        append_log: Callable[[JobRecord, str], Awaitable[None]],
        append_event: Callable[[JobRecord, EventBroker | None, dict[str, object]], Awaitable[None]],
        tracked_tree_is_clean_fn: Callable[[Path], bool],
        run_git_revert_fn: Callable[[Path, str], GitCommandResult],
        abort_git_revert_fn: Callable[[Path], GitAbortResult],
        verify_failed_revert_postconditions_fn: Callable[..., RevertFailureVerification],
    ) -> None:
        self._load_job_record_any = load_job_record_any
        self._resolve_target_root = resolve_target_root
        self._capture_head_sha_for_job = capture_head_sha_for_job
        self._append_log = append_log
        self._append_event = append_event
        self._tracked_tree_is_clean_fn = tracked_tree_is_clean_fn
        self._run_git_revert_fn = run_git_revert_fn
        self._abort_git_revert_fn = abort_git_revert_fn
        self._verify_failed_revert_postconditions_fn = verify_failed_revert_postconditions_fn

    async def run(
        self,
        job: JobRecord,
        broker: EventBroker | None,
    ) -> tuple[int, str | None]:
        await self._append_event(
            job,
            broker,
            {
                "type": "hello",
                "protocol": "patchhub_internal/1",
                "runner_mode": "revert_job",
                "issue_id": str(job.issue_id or ""),
            },
        )
        source_job_id = str(job.revert_source_job_id or "").strip()
        if not source_job_id:
            return await self._fail(job, broker, "revert source job is missing")
        source_job = await self._load_job_record_any(source_job_id)
        if source_job is None:
            return await self._fail(job, broker, f"revert source job not found: {source_job_id}")
        source_sha = str(source_job.run_end_sha or "").strip()
        if not source_sha:
            return await self._fail(
                job,
                broker,
                f"revert source job missing run_end_sha: {source_job_id}",
            )
        try:
            target_root = self._resolve_target_root(job)
            clean = await asyncio.to_thread(self._tracked_tree_is_clean_fn, target_root)
        except RevertJobRuntimeError as exc:
            return await self._fail(job, broker, str(exc))
        if not clean:
            return await self._fail(job, broker, "tracked working tree/index is not clean")
        await self._emit_log(
            job,
            broker,
            message=f"git revert --no-edit {source_sha}",
            kind="DO",
            summary=True,
        )
        result = await asyncio.to_thread(self._run_git_revert_fn, target_root, source_sha)
        await self._emit_subprocess_output(job, broker, stdout=result.stdout, stderr=result.stderr)
        if int(result.return_code) == 0:
            try:
                job.run_end_sha = await self._capture_head_sha_for_job(job)
            except RevertJobRuntimeError as exc:
                return await self._fail(
                    job,
                    broker,
                    f"revert commit created but cannot capture HEAD: {exc}",
                )
            await self._emit_log(
                job,
                broker,
                message="revert commit created",
                kind="OK",
                sev="INFO",
                summary=True,
            )
            await self._append_event(job, broker, {"type": "result", "ok": True, "return_code": 0})
            return 0, None
        abort = await asyncio.to_thread(self._abort_git_revert_fn, target_root)
        if abort.result is not None:
            await self._emit_subprocess_output(
                job,
                broker,
                stdout=abort.result.stdout,
                stderr=abort.result.stderr,
            )
        message = f"git revert failed with rc={int(result.return_code)}"
        if abort.attempted and abort.result is not None and abort.result.return_code != 0:
            message = f"{message}; git revert --abort failed with rc={abort.result.return_code}"
        verification = await asyncio.to_thread(
            self._verify_failed_revert_postconditions_fn,
            target_root,
            expected_head=str(job.run_start_sha or ""),
        )
        if verification.actual_head:
            job.run_end_sha = verification.actual_head
        if verification.error:
            message = f"{message}; {verification.error}"
        await self._emit_log(job, broker, message=message, kind="FAIL", sev="ERROR", summary=True)
        await self._append_event(
            job,
            broker,
            {"type": "result", "ok": False, "return_code": int(result.return_code)},
        )
        return int(result.return_code), message

    async def _fail(
        self,
        job: JobRecord,
        broker: EventBroker | None,
        message: str,
    ) -> tuple[int, str]:
        await self._emit_log(job, broker, message=message, kind="FAIL", sev="ERROR", summary=True)
        await self._append_event(job, broker, {"type": "result", "ok": False})
        return 1, message

    async def _emit_log(
        self,
        job: JobRecord,
        broker: EventBroker | None,
        *,
        message: str,
        kind: str,
        sev: str = "INFO",
        ch: str = "CORE",
        summary: bool = False,
    ) -> None:
        payload: dict[str, object] = {
            "type": "log",
            "ch": ch,
            "sev": sev,
            "kind": kind,
            "msg": str(message or ""),
            "stage": "revert",
        }
        if summary:
            payload["summary"] = True
        await self._append_log(job, str(message or ""))
        await self._append_event(job, broker, payload)

    async def _emit_subprocess_output(
        self,
        job: JobRecord,
        broker: EventBroker | None,
        *,
        stdout: str,
        stderr: str,
    ) -> None:
        specs = ((stdout, "INFO", "SUBPROCESS_STDOUT"), (stderr, "WARNING", "SUBPROCESS_STDERR"))
        for stream, sev, kind in specs:
            for raw_line in str(stream or "").splitlines():
                line = str(raw_line).rstrip("\n")
                if not line:
                    continue
                await self._append_log(job, line)
                await self._append_event(
                    job,
                    broker,
                    {
                        "type": "log",
                        "ch": "DETAIL",
                        "sev": sev,
                        "kind": kind,
                        "msg": line,
                        "stage": "revert",
                    },
                )


def build_revert_job_handler(
    *,
    jobs_root: Path,
    job_db: WebJobsDatabase | None,
    current_job_lookup: Callable[[str], Awaitable[JobRecord | None]],
    target_repo_roots: Mapping[str, Path],
    capture_head_sha_for_job: Callable[[JobRecord], Awaitable[str]],
    job_dir_for_id: Callable[[str], Path],
    event_path_for_job: Callable[[JobRecord], Path],
    tracked_tree_is_clean_fn: Callable[[Path], bool],
    run_git_revert_fn: Callable[[Path, str], GitCommandResult],
    abort_git_revert_fn: Callable[[Path], GitAbortResult],
    verify_failed_revert_postconditions_fn: Callable[..., RevertFailureVerification],
) -> RevertJobHandler:
    async def load_job_record_any(job_id: str) -> JobRecord | None:
        current = await current_job_lookup(job_id)
        if current is not None:
            return current
        if job_db is not None:
            return await asyncio.to_thread(job_db.load_job_record, job_id)
        return await asyncio.to_thread(load_legacy_job_record, jobs_root, job_id)

    def resolve_target_root(job: JobRecord) -> Path:
        token = str(job.effective_runner_target_repo or "").strip()
        return resolve_target_repo_root(target_repo_roots, token)

    async def append_log(job: JobRecord, line: str) -> None:
        text = str(line or "").rstrip("\n")
        if job_db is not None:
            await asyncio.to_thread(job_db.append_log_line, job.job_id, text)
            return
        await asyncio.to_thread(_append_line_sync, job_dir_for_id(job.job_id) / "runner.log", text)

    async def append_event(
        job: JobRecord,
        broker: EventBroker | None,
        payload: dict[str, object],
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if job_db is not None:
            seq = await asyncio.to_thread(job_db.append_event_line, job.job_id, raw)
        else:
            seq = await asyncio.to_thread(_append_line_sync, event_path_for_job(job), raw)
        if broker is not None:
            broker.publish(raw, seq)

    return RevertJobHandler(
        load_job_record_any=load_job_record_any,
        resolve_target_root=resolve_target_root,
        capture_head_sha_for_job=capture_head_sha_for_job,
        append_log=append_log,
        append_event=append_event,
        tracked_tree_is_clean_fn=tracked_tree_is_clean_fn,
        run_git_revert_fn=run_git_revert_fn,
        abort_git_revert_fn=abort_git_revert_fn,
        verify_failed_revert_postconditions_fn=verify_failed_revert_postconditions_fn,
    )


def resolve_target_repo_root(target_repo_roots: Mapping[str, Path], target_repo: str) -> Path:
    token = str(target_repo or "").strip()
    if not token:
        raise RevertJobRuntimeError("missing effective_runner_target_repo")
    root = target_repo_roots.get(token)
    if root is None:
        raise RevertJobRuntimeError(f"unknown target repo token: {token}")
    return Path(root).resolve()


def capture_head_sha(repo_root: Path) -> str:
    result = _run_git(repo_root, ["git", "rev-parse", "HEAD"])
    if result.return_code != 0:
        raise RevertJobRuntimeError(_git_error("cannot capture HEAD", result))
    sha = str(result.stdout or "").strip()
    if not sha:
        raise RevertJobRuntimeError("cannot capture HEAD: empty output")
    return sha


def tracked_tree_is_clean(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["git", "status", "--porcelain", "--untracked-files=no"])
    if result.return_code != 0:
        raise RevertJobRuntimeError(_git_error("cannot inspect working tree", result))
    return not bool(str(result.stdout or "").strip())


def run_git_revert(repo_root: Path, source_sha: str) -> GitCommandResult:
    return _run_git(repo_root, ["git", "revert", "--no-edit", str(source_sha or "")])


def revert_state_active(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["git", "rev-parse", "-q", "--verify", "REVERT_HEAD"])
    return result.return_code == 0 and bool(str(result.stdout or "").strip())


def abort_git_revert(repo_root: Path) -> GitAbortResult:
    if not revert_state_active(repo_root):
        return GitAbortResult(attempted=False, result=None)
    return GitAbortResult(attempted=True, result=_run_git(repo_root, ["git", "revert", "--abort"]))


def verify_failed_revert_postconditions(
    repo_root: Path,
    *,
    expected_head: str,
) -> RevertFailureVerification:
    notes: list[str] = []
    actual_head: str | None = None
    try:
        actual_head = capture_head_sha(repo_root)
    except RevertJobRuntimeError as exc:
        notes.append(str(exc))
    try:
        clean = tracked_tree_is_clean(repo_root)
    except RevertJobRuntimeError as exc:
        notes.append(str(exc))
    else:
        if not clean:
            notes.append("tracked working tree/index is not clean after failed revert")
    if actual_head and str(expected_head or "").strip() and actual_head != expected_head:
        notes.append("HEAD changed after failed revert")
    return RevertFailureVerification(actual_head=actual_head, error="; ".join(notes) or None)


def _append_line_sync(path: Path, line: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(str(line or "") + "\n")
        return int(f.tell())


def _run_git(repo_root: Path, argv: list[str]) -> GitCommandResult:
    proc = subprocess.run(argv, cwd=str(repo_root), check=False, capture_output=True, text=True)
    return GitCommandResult(
        return_code=int(proc.returncode),
        stdout=str(proc.stdout or ""),
        stderr=str(proc.stderr or ""),
    )


def _git_error(prefix: str, result: GitCommandResult) -> str:
    details: list[str] = [str(prefix or "git command failed")]
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        details.append(f"stdout={stdout}")
    if stderr:
        details.append(f"stderr={stderr}")
    details.append(f"rc={int(result.return_code)}")
    return "; ".join(details)
