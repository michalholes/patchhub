from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patchhub.models import JobRecord
from patchhub.rollback_preflight import (
    RollbackPreflightError,
    preflight_matches_token,
    run_rollback_preflight,
    validate_source_job_authority,
)

from .revert_job_runtime import EventBroker


@dataclass(frozen=True)
class RollbackRequest:
    source_job_id: str
    scope_kind: str
    selected_repo_paths: list[str]
    rollback_preflight_token: str


class RollbackRuntimeError(RuntimeError):
    pass


class RollbackJobHandler:
    def __init__(
        self,
        *,
        jobs_root: Path,
        load_job_record_any: Callable[[str], Awaitable[JobRecord | None]],
        load_all_jobs: Callable[[], Awaitable[list[JobRecord]]],
        target_repo_roots: Mapping[str, Path],
        capture_head_sha_for_job: Callable[[JobRecord], Awaitable[str]],
        append_log: Callable[[JobRecord, str], Awaitable[None]],
        append_event: Callable[[JobRecord, EventBroker | None, dict[str, object]], Awaitable[None]],
    ) -> None:
        self._jobs_root = Path(jobs_root)
        self._load_job_record_any = load_job_record_any
        self._load_all_jobs = load_all_jobs
        self._target_repo_roots = {str(k): Path(v).resolve() for k, v in target_repo_roots.items()}
        self._capture_head_sha_for_job = capture_head_sha_for_job
        self._append_log = append_log
        self._append_event = append_event

    async def run(self, job: JobRecord, broker: EventBroker | None) -> tuple[int, str | None]:
        request = self._load_request(job)
        source_job = await self._load_job_record_any(request.source_job_id)
        if source_job is None:
            return await self._fail(job, broker, "rollback source job not found")
        try:
            (
                manifest_rel_path,
                manifest_hash,
                _kind,
                _source_ref,
            ) = validate_source_job_authority(source_job)
            preflight = run_rollback_preflight(
                jobs_root=self._jobs_root,
                target_repo_roots=dict(self._target_repo_roots),
                source_job=source_job,
                source_manifest_rel_path=manifest_rel_path,
                source_manifest_hash=manifest_hash,
                scope_kind=request.scope_kind,
                selected_repo_paths=request.selected_repo_paths,
                all_jobs=await self._load_all_jobs(),
            )
        except (RollbackPreflightError, ValueError) as exc:
            return await self._fail(job, broker, f"rollback preflight failed: {exc}")
        if not preflight_matches_token(preflight, request.rollback_preflight_token):
            return await self._fail(job, broker, "rollback state changed after preview")
        if not preflight.get("can_execute"):
            return await self._fail(
                job,
                broker,
                "rollback cannot execute until guided blockers are resolved",
            )
        token = str(source_job.effective_runner_target_repo or "").strip()
        target_root = self._resolve_target_root(token)
        steps = await self._build_execution_steps(source_job, preflight)
        if not steps:
            return await self._fail(job, broker, "rollback execution plan is empty")
        await self._emit_log(job, broker, "rollback execution started", kind="OK")
        for step in steps:
            message = step["message"]
            await self._emit_log(job, broker, message, kind="INFO")
            rc, error = await asyncio.to_thread(
                self._apply_step,
                target_root,
                step["run_start_sha"],
                list(step["restore_paths"]),
                step["commit_message"],
            )
            if rc != 0:
                return await self._fail(job, broker, error or "rollback step failed")
        try:
            job.run_end_sha = await self._capture_head_sha_for_job(job)
        except Exception as exc:
            return await self._fail(
                job,
                broker,
                f"rollback commit created but cannot capture HEAD: {exc}",
            )
        await self._emit_log(job, broker, "rollback execution finished", kind="OK")
        await self._append_event(job, broker, {"type": "result", "ok": True, "return_code": 0})
        return 0, None

    async def _build_execution_steps(
        self,
        source_job: JobRecord,
        preflight: dict[str, Any],
    ) -> list[dict[str, Any]]:
        all_jobs = await self._load_all_jobs()
        by_id = {str(item.job_id): item for item in all_jobs}
        steps: list[dict[str, Any]] = []
        for chain in list(preflight.get("chain_steps") or []):
            chain_job = by_id.get(str(chain.get("job_id") or ""))
            if chain_job is None:
                continue
            steps.append(
                {
                    "run_start_sha": str(chain_job.run_start_sha or ""),
                    "restore_paths": list(chain.get("selected_repo_paths") or []),
                    "commit_message": f"PatchHub roll-back overlap {chain_job.job_id}",
                    "message": f"rolling back newer overlap {chain_job.job_id}",
                }
            )
        steps.append(
            {
                "run_start_sha": str(source_job.run_start_sha or ""),
                "restore_paths": list(preflight.get("restore_paths") or []),
                "commit_message": f"PatchHub roll-back {source_job.job_id}",
                "message": f"rolling back source job {source_job.job_id}",
            }
        )
        return steps

    def _load_request(self, job: JobRecord) -> RollbackRequest:
        path = self._jobs_root / str(job.job_id or "") / "rollback_request.json"
        if not path.is_file():
            raise RollbackRuntimeError("missing rollback request payload")
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise RollbackRuntimeError("invalid rollback request payload")
        return RollbackRequest(
            source_job_id=str(parsed.get("source_job_id") or ""),
            scope_kind=str(parsed.get("scope_kind") or ""),
            selected_repo_paths=[
                str(item) for item in list(parsed.get("selected_repo_paths") or [])
            ],
            rollback_preflight_token=str(parsed.get("rollback_preflight_token") or ""),
        )

    def _resolve_target_root(self, token: str) -> Path:
        root = self._target_repo_roots.get(str(token or "").strip())
        if root is None:
            raise RollbackRuntimeError("unknown rollback target repo")
        return Path(root).resolve()

    def _apply_step(
        self,
        repo_root: Path,
        run_start_sha: str,
        restore_paths: list[str],
        commit_message: str,
    ) -> tuple[int, str | None]:
        if not run_start_sha or not restore_paths:
            return 1, "rollback step is missing run_start_sha or restore paths"
        result = _run_git(
            repo_root,
            [
                "git",
                "restore",
                "--source",
                run_start_sha,
                "--staged",
                "--worktree",
                "--",
                *restore_paths,
            ],
        )
        if result.returncode != 0:
            return int(result.returncode), _git_error("git restore failed", result)
        if not _has_changes(repo_root, restore_paths):
            return 0, None
        commit = _run_git(repo_root, ["git", "commit", "-m", commit_message])
        if commit.returncode != 0:
            return int(commit.returncode), _git_error("git commit failed", commit)
        return 0, None

    async def _fail(
        self,
        job: JobRecord,
        broker: EventBroker | None,
        message: str,
    ) -> tuple[int, str]:
        await self._emit_log(job, broker, message, kind="FAIL", sev="ERROR")
        await self._append_event(job, broker, {"type": "result", "ok": False})
        return 1, message

    async def _emit_log(
        self,
        job: JobRecord,
        broker: EventBroker | None,
        message: str,
        *,
        kind: str,
        sev: str = "INFO",
    ) -> None:
        await self._append_log(job, str(message or ""))
        await self._append_event(
            job,
            broker,
            {
                "type": "log",
                "ch": "CORE",
                "sev": sev,
                "kind": kind,
                "msg": str(message or ""),
                "stage": "rollback",
            },
        )


def build_rollback_job_handler(
    *,
    jobs_root: Path,
    load_job_record_any: Callable[[str], Awaitable[JobRecord | None]],
    load_all_jobs: Callable[[], Awaitable[list[JobRecord]]],
    target_repo_roots: Mapping[str, Path],
    capture_head_sha_for_job: Callable[[JobRecord], Awaitable[str]],
    append_log: Callable[[JobRecord, str], Awaitable[None]],
    append_event: Callable[[JobRecord, EventBroker | None, dict[str, object]], Awaitable[None]],
) -> RollbackJobHandler:
    return RollbackJobHandler(
        jobs_root=jobs_root,
        load_job_record_any=load_job_record_any,
        load_all_jobs=load_all_jobs,
        target_repo_roots=target_repo_roots,
        capture_head_sha_for_job=capture_head_sha_for_job,
        append_log=append_log,
        append_event=append_event,
    )


def _has_changes(repo_root: Path, restore_paths: list[str]) -> bool:
    result = _run_git(repo_root, ["git", "status", "--porcelain", "--", *restore_paths])
    if result.returncode != 0:
        raise RollbackRuntimeError(_git_error("cannot inspect rollback changes", result))
    return bool(str(result.stdout or "").strip())


def _run_git(repo_root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(repo_root), check=False, capture_output=True, text=True)


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> str:
    parts = [str(prefix or "git command failed"), f"rc={int(result.returncode)}"]
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    return "; ".join(parts)
