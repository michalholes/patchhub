# ruff: noqa: E402
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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


class _CommitExecutor:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

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
        del argv, cwd, post_exit_grace_s, job_db, job_id
        (self.repo_root / "a.py").write_text('print("patched")\n', encoding="utf-8")
        _git(self.repo_root, "add", "a.py")
        _git(self.repo_root, "commit", "-m", "Apply patchhub change")
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("runner\n", encoding="utf-8")
        return type(
            "ExecResult",
            (),
            {"return_code": 0, "stdout_tail_timed_out": False},
        )()


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc


def _init_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "patchhub@example.com")
    _git(repo_root, "config", "user.name", "PatchHub")


def _head_sha(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD").stdout.strip()


def _tracked_clean(repo_root: Path) -> bool:
    return not _git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
    ).stdout.strip()


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


class TestPatchhubRevertJobQueue(unittest.IsolatedAsyncioTestCase):
    async def test_revert_job_success_restores_previous_tree_and_captures_shas(
        self,
    ) -> None:
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
            source_job = JobRecord(
                job_id="job-source-success",
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
            db.upsert_job(source_job)
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
                job_id="job-revert-success",
                created_utc="2026-03-24T10:01:00Z",
                mode="revert_job",
                issue_id="380",
                commit_summary="Revert source",
                patch_basename=None,
                raw_command="patchhub revert_job job-source-success",
                canonical_command=["patchhub", "revert_job", "job-source-success"],
                effective_runner_target_repo="patchhub",
                revert_source_job_id="job-source-success",
            )

            await queue.start()
            try:
                await queue.enqueue(revert_job)
                finished = await _wait_for_terminal(queue, revert_job.job_id)
            finally:
                with contextlib.suppress(asyncio.CancelledError):
                    await queue.stop()

            event_rows, _ = db.read_event_tail(revert_job.job_id, lines=50)
            event_text = "\n".join(row.raw_line for row in event_rows)
            self.assertEqual(finished.status, "success")
            self.assertEqual(finished.run_start_sha, source_sha)
            self.assertNotEqual(finished.run_end_sha, source_sha)
            self.assertEqual((repo_root / "a.py").read_text(encoding="utf-8"), 'print("base")\n')
            self.assertTrue(_tracked_clean(repo_root))
            self.assertIn('"protocol":"patchhub_internal/1"', event_text)
            self.assertIn('"type":"result","ok":true', event_text)

    async def test_revert_job_conflict_aborts_and_preserves_clean_head(self) -> None:
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
            (repo_root / "a.py").write_text('print("later")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Later conflicting change")
            latest_sha = _head_sha(repo_root)

            db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
            source_job = JobRecord(
                job_id="job-source-conflict",
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
            db.upsert_job(source_job)
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
                job_id="job-revert-conflict",
                created_utc="2026-03-24T10:01:00Z",
                mode="revert_job",
                issue_id="380",
                commit_summary="Revert source",
                patch_basename=None,
                raw_command="patchhub revert_job job-source-conflict",
                canonical_command=["patchhub", "revert_job", "job-source-conflict"],
                effective_runner_target_repo="patchhub",
                revert_source_job_id="job-source-conflict",
            )

            await queue.start()
            try:
                await queue.enqueue(revert_job)
                finished = await _wait_for_terminal(queue, revert_job.job_id)
            finally:
                with contextlib.suppress(asyncio.CancelledError):
                    await queue.stop()

            self.assertEqual(finished.status, "fail")
            self.assertEqual(finished.run_start_sha, latest_sha)
            self.assertEqual(finished.run_end_sha, latest_sha)
            self.assertEqual(_head_sha(repo_root), latest_sha)
            self.assertTrue(_tracked_clean(repo_root))
            self.assertEqual((repo_root / "a.py").read_text(encoding="utf-8"), 'print("later")\n')
            self.assertIn("git revert failed", str(finished.error or ""))

    async def test_normal_job_captures_start_and_end_sha_for_new_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            _init_repo(repo_root)
            (repo_root / "a.py").write_text('print("base")\n', encoding="utf-8")
            _git(repo_root, "add", "a.py")
            _git(repo_root, "commit", "-m", "Base")
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_CommitExecutor(repo_root),
                target_repo_roots={"patchhub": repo_root},
            )
            job = JobRecord(
                job_id="job-normal-sha",
                created_utc="2026-03-24T10:00:00Z",
                mode="patch",
                issue_id="380",
                commit_summary="Apply change",
                patch_basename="issue_380_v1.zip",
                raw_command="python3 scripts/am_patch.py 380",
                canonical_command=["python3", "scripts/am_patch.py", "380"],
                effective_runner_target_repo="patchhub",
            )

            async def quick_pump(
                *,
                socket_path: str,
                jsonl_path: Path,
                publish=None,
                command_channel=None,
                connect_timeout_s: float = 10.0,
                retry_sleep_s: float = 0.25,
            ) -> None:
                del socket_path, command_channel, connect_timeout_s, retry_sleep_s
                line = '{"type":"log","msg":"tail"}'
                with jsonl_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    end_offset = handle.tell()
                if publish is not None:
                    publish(line, end_offset)

            with patch.object(
                async_queue_mod,
                "start_event_pump",
                side_effect=quick_pump,
            ):
                await queue.start()
                try:
                    await queue.enqueue(job)
                    finished = await _wait_for_terminal(queue, job.job_id)
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.stop()

            self.assertEqual(finished.status, "success")
            self.assertTrue(str(finished.run_start_sha or ""))
            self.assertTrue(str(finished.run_end_sha or ""))
            self.assertNotEqual(finished.run_start_sha, finished.run_end_sha)
