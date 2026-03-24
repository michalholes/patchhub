# ruff: noqa: E402
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import patchhub.asgi.async_queue as async_queue_mod
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


class _NoopExecutor:
    async def is_running(self) -> bool:
        return False

    async def terminate(self, *, grace_s: int = 3) -> bool:
        del grace_s
        return False

    async def run(
        self,
        argv: list[str],
        cwd: Path,
        log_path: Path | None,
        *,
        post_exit_grace_s: int = 5,
        job_db: WebJobsDatabase | None = None,
        job_id: str | None = None,
    ):
        del argv, cwd, log_path, post_exit_grace_s, job_db, job_id
        raise AssertionError("revert_job must not call executor.run")


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "patchhub@example.com")
    _git(repo_root, "config", "user.name", "PatchHub")


def _head_sha(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD").stdout.strip()


async def _wait_for_terminal(
    queue: async_queue_mod.AsyncJobQueue,
    job_id: str,
) -> JobRecord:
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        job = await queue.get_job(job_id)
        if job is not None and job.status in {"success", "fail", "canceled"}:
            return job
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"{job_id} did not finish")
        await asyncio.sleep(0.01)


class TestPatchhubRevertJobQueueGuards(unittest.IsolatedAsyncioTestCase):
    async def test_revert_job_success_uses_only_start_and_end_head_capture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            patches_root = repo_root / "patches"
            jobs_root = patches_root / "artifacts" / "web_jobs"
            _init_repo(repo_root)
            (repo_root / "a.py").write_text('print("base")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Base")
            base_sha = _head_sha(repo_root)
            (repo_root / "a.py").write_text('print("bug")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Buggy change")
            source_sha = _head_sha(repo_root)

            db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
            db.upsert_job(
                JobRecord(
                    job_id="job-source-capture",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Buggy change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=base_sha,
                    run_end_sha=source_sha,
                )
            )
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )
            revert_job = JobRecord(
                job_id="job-revert-capture",
                created_utc="2026-03-24T10:01:00Z",
                mode="revert_job",
                issue_id="380",
                commit_summary="Revert source",
                patch_basename=None,
                raw_command="patchhub revert_job job-source-capture",
                canonical_command=["patchhub", "revert_job", "job-source-capture"],
                effective_runner_target_repo="patchhub",
                revert_source_job_id="job-source-capture",
            )

            original_capture = async_queue_mod.capture_head_sha
            capture_calls = 0

            def counting_capture(repo_root_arg: Path) -> str:
                nonlocal capture_calls
                capture_calls += 1
                if capture_calls > 2:
                    raise AssertionError("unexpected extra HEAD capture")
                return original_capture(repo_root_arg)

            with patch.object(
                async_queue_mod,
                "capture_head_sha",
                side_effect=counting_capture,
            ):
                await queue.start()
                try:
                    await queue.enqueue(revert_job)
                    finished = await _wait_for_terminal(queue, revert_job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.status, "success")
            self.assertEqual(capture_calls, 2)

    async def test_revert_job_fails_when_end_head_capture_fails_after_commit(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            patches_root = repo_root / "patches"
            jobs_root = patches_root / "artifacts" / "web_jobs"
            _init_repo(repo_root)
            (repo_root / "a.py").write_text('print("base")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Base")
            base_sha = _head_sha(repo_root)
            (repo_root / "a.py").write_text('print("bug")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Buggy change")
            source_sha = _head_sha(repo_root)

            db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
            db.upsert_job(
                JobRecord(
                    job_id="job-source-capture-fail",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Buggy change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=base_sha,
                    run_end_sha=source_sha,
                )
            )
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )
            revert_job = JobRecord(
                job_id="job-revert-capture-fail",
                created_utc="2026-03-24T10:01:00Z",
                mode="revert_job",
                issue_id="380",
                commit_summary="Revert source",
                patch_basename=None,
                raw_command="patchhub revert_job job-source-capture-fail",
                canonical_command=["patchhub", "revert_job", "job-source-capture-fail"],
                effective_runner_target_repo="patchhub",
                revert_source_job_id="job-source-capture-fail",
            )

            original_capture = async_queue_mod.capture_head_sha
            capture_calls = 0

            def failing_second_capture(repo_root_arg: Path) -> str:
                nonlocal capture_calls
                capture_calls += 1
                if capture_calls == 2:
                    raise async_queue_mod.RevertJobRuntimeError("cannot capture after commit")
                return original_capture(repo_root_arg)

            with patch.object(
                async_queue_mod,
                "capture_head_sha",
                side_effect=failing_second_capture,
            ):
                await queue.start()
                try:
                    await queue.enqueue(revert_job)
                    finished = await _wait_for_terminal(queue, revert_job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.status, "fail")
            self.assertIn(
                "revert commit created but cannot capture HEAD",
                str(finished.error or ""),
            )
            self.assertIsNone(finished.run_end_sha)

    async def test_revert_job_reports_unclean_repo_when_abort_does_not_restore_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            patches_root = repo_root / "patches"
            jobs_root = patches_root / "artifacts" / "web_jobs"
            _init_repo(repo_root)
            (repo_root / "a.py").write_text('print("base")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Base")
            base_sha = _head_sha(repo_root)
            (repo_root / "a.py").write_text('print("bug")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Buggy change")
            source_sha = _head_sha(repo_root)

            db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
            db.upsert_job(
                JobRecord(
                    job_id="job-source-abort",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Buggy change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=base_sha,
                    run_end_sha=source_sha,
                )
            )
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )
            revert_job = JobRecord(
                job_id="job-revert-abort",
                created_utc="2026-03-24T10:01:00Z",
                mode="revert_job",
                issue_id="380",
                commit_summary="Revert source",
                patch_basename=None,
                raw_command="patchhub revert_job job-source-abort",
                canonical_command=["patchhub", "revert_job", "job-source-abort"],
                effective_runner_target_repo="patchhub",
                revert_source_job_id="job-source-abort",
            )

            failed_revert = SimpleNamespace(return_code=1, stdout="", stderr="conflict")
            failed_abort = SimpleNamespace(
                attempted=True,
                result=SimpleNamespace(return_code=1, stdout="", stderr="abort failed"),
            )

            with (
                patch.object(async_queue_mod, "run_git_revert", return_value=failed_revert),
                patch.object(async_queue_mod, "abort_git_revert", return_value=failed_abort),
                patch.object(
                    async_queue_mod,
                    "verify_failed_revert_postconditions",
                    return_value=SimpleNamespace(
                        actual_head=source_sha,
                        error="tracked working tree/index is not clean after failed revert",
                    ),
                ),
            ):
                await queue.start()
                try:
                    await queue.enqueue(revert_job)
                    finished = await _wait_for_terminal(queue, revert_job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.status, "fail")
            self.assertIn(
                "tracked working tree/index is not clean after failed revert",
                str(finished.error or ""),
            )
