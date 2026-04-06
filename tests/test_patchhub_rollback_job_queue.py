# ruff: noqa: E402
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import patchhub.asgi.async_queue as async_queue_mod
import patchhub.asgi.rollback_runtime as rollback_runtime_mod
from patchhub.models import JobRecord
from patchhub.rollback_preflight import run_rollback_preflight, validate_source_job_authority
from patchhub.rollback_scope_manifest import build_manifest_for_job
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
        raise AssertionError("rollback must not call executor.run")


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


def _persist_source_job_with_manifest(
    *,
    repo_root: Path,
    jobs_root: Path,
    db: WebJobsDatabase,
    job: JobRecord,
) -> JobRecord:
    manifest = build_manifest_for_job(
        repo_root=repo_root,
        source_job_id=job.job_id,
        issue_id=str(job.issue_id or ""),
        selected_target_repo_token="patchhub",
        effective_runner_target_repo="patchhub",
        run_start_sha=str(job.run_start_sha or ""),
        run_end_sha=str(job.run_end_sha or ""),
        authority_kind="github",
        authority_source_ref=f"issue:{str(job.issue_id or '')}",
    )
    job.rollback_scope_manifest_rel_path = None
    job.rollback_scope_manifest_hash = None
    job.rollback_authority_kind = str(manifest.get("rollback_authority_kind") or "")
    job.rollback_authority_source_ref = str(manifest.get("rollback_authority_source_ref") or "")
    db.upsert_job(job)
    db.upsert_manifest_authority(job, manifest, count_as_job_change=False)
    return job


def _persist_rollback_request(
    db: WebJobsDatabase,
    *,
    job_id: str,
    payload: dict[str, object],
) -> None:
    db.upsert_request_authority(
        job_id=job_id,
        source_job_id=str(payload.get("source_job_id") or ""),
        scope_kind=str(payload.get("scope_kind") or ""),
        selected_repo_paths=[str(item) for item in list(payload.get("selected_repo_paths") or [])],
        rollback_preflight_token=str(payload.get("rollback_preflight_token") or ""),
        count_as_job_change=False,
    )


class TestPatchhubRollbackJobQueue(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_executes_against_db_only_source_job(self) -> None:
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
            source_job = _persist_source_job_with_manifest(
                repo_root=repo_root,
                jobs_root=jobs_root,
                db=db,
                job=JobRecord(
                    job_id="job-source-db-only",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="389",
                    commit_summary="Buggy change",
                    patch_basename="issue_389_v1.zip",
                    raw_command="python3 scripts/am_patch.py 389",
                    canonical_command=["python3", "scripts/am_patch.py", "389"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=base_sha,
                    run_end_sha=source_sha,
                ),
            )
            assert not (jobs_root / source_job.job_id / "rollback_scope_manifest.json").exists()
            rel_path, manifest_hash, _kind, _ref = validate_source_job_authority(source_job)
            preflight = run_rollback_preflight(
                jobs_root=jobs_root,
                target_repo_roots={"patchhub": repo_root},
                source_job=source_job,
                source_manifest_rel_path=rel_path,
                source_manifest_hash=manifest_hash,
                scope_kind="full",
                selected_repo_paths=[],
                all_jobs=[source_job],
                load_manifest_for_job=lambda job: db.load_rollback_manifest(job.job_id),
            )
            rollback_job = JobRecord(
                job_id="job-rollback-db-only",
                created_utc="2026-03-24T10:01:00Z",
                mode="rollback",
                issue_id="389",
                commit_summary="Roll-back source",
                patch_basename=None,
                raw_command="patchhub rollback job-source-db-only",
                canonical_command=["patchhub", "rollback", "job-source-db-only"],
                effective_runner_target_repo="patchhub",
                rollback_source_job_id="job-source-db-only",
            )
            _persist_rollback_request(
                db,
                job_id=rollback_job.job_id,
                payload={
                    "source_job_id": source_job.job_id,
                    "scope_kind": "full",
                    "selected_repo_paths": [],
                    "rollback_preflight_token": preflight["rollback_preflight_token"],
                },
            )
            assert not (jobs_root / rollback_job.job_id / "rollback_request.json").exists()
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )

            await queue.start()
            try:
                await queue.enqueue(rollback_job)
                finished = await _wait_for_terminal(queue, rollback_job.job_id)
            finally:
                with contextlib.suppress(asyncio.CancelledError):
                    await queue.stop()

            event_rows, _ = db.read_event_tail(rollback_job.job_id, lines=50)
            event_text = "\n".join(row.raw_line for row in event_rows)
            self.assertEqual(finished.status, "success")
            self.assertEqual(finished.run_start_sha, source_sha)
            self.assertNotEqual(finished.run_end_sha, source_sha)
            self.assertEqual((repo_root / "a.py").read_text(encoding="utf-8"), 'print("base")\n')
            self.assertTrue(_tracked_clean(repo_root))
            self.assertIn("rollback execution finished", event_text)
            self.assertIn('"type":"result","ok":true', event_text)
            self.assertFalse(
                (jobs_root / source_job.job_id / "rollback_scope_manifest.json").exists()
            )
            self.assertFalse((jobs_root / rollback_job.job_id / "rollback_request.json").exists())

    async def test_rollback_executes_newer_overlap_chain_from_db_only_job_corpus(self) -> None:
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
            _git(repo_root, "commit", "-m", "Later change")
            later_sha = _head_sha(repo_root)

            db = WebJobsDatabase(load_web_jobs_db_config(repo_root, patches_root))
            source_job = _persist_source_job_with_manifest(
                repo_root=repo_root,
                jobs_root=jobs_root,
                db=db,
                job=JobRecord(
                    job_id="job-source-chain",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="389",
                    commit_summary="Buggy change",
                    patch_basename="issue_389_v1.zip",
                    raw_command="python3 scripts/am_patch.py 389",
                    canonical_command=["python3", "scripts/am_patch.py", "389"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=base_sha,
                    run_end_sha=source_sha,
                ),
            )
            later_job = _persist_source_job_with_manifest(
                repo_root=repo_root,
                jobs_root=jobs_root,
                db=db,
                job=JobRecord(
                    job_id="job-later-overlap",
                    created_utc="2026-03-24T10:02:00Z",
                    mode="patch",
                    issue_id="390",
                    commit_summary="Later change",
                    patch_basename="issue_390_v1.zip",
                    raw_command="python3 scripts/am_patch.py 390",
                    canonical_command=["python3", "scripts/am_patch.py", "390"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha=source_sha,
                    run_end_sha=later_sha,
                ),
            )
            rel_path, manifest_hash, _kind, _ref = validate_source_job_authority(source_job)
            preflight = run_rollback_preflight(
                jobs_root=jobs_root,
                target_repo_roots={"patchhub": repo_root},
                source_job=source_job,
                source_manifest_rel_path=rel_path,
                source_manifest_hash=manifest_hash,
                scope_kind="full",
                selected_repo_paths=[],
                all_jobs=[source_job, later_job],
                load_manifest_for_job=lambda job: db.load_rollback_manifest(job.job_id),
            )
            self.assertTrue(preflight["chain_required"])
            rollback_job = JobRecord(
                job_id="job-rollback-chain",
                created_utc="2026-03-24T10:03:00Z",
                mode="rollback",
                issue_id="389",
                commit_summary="Roll-back source chain",
                patch_basename=None,
                raw_command="patchhub rollback job-source-chain",
                canonical_command=["patchhub", "rollback", "job-source-chain"],
                effective_runner_target_repo="patchhub",
                rollback_source_job_id="job-source-chain",
            )
            _persist_rollback_request(
                db,
                job_id=rollback_job.job_id,
                payload={
                    "source_job_id": source_job.job_id,
                    "scope_kind": "full",
                    "selected_repo_paths": [],
                    "rollback_preflight_token": preflight["rollback_preflight_token"],
                },
            )
            assert not (jobs_root / rollback_job.job_id / "rollback_request.json").exists()
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )

            await queue.start()
            try:
                await queue.enqueue(rollback_job)
                finished = await _wait_for_terminal(queue, rollback_job.job_id)
            finally:
                with contextlib.suppress(asyncio.CancelledError):
                    await queue.stop()

            event_rows, _ = db.read_event_tail(rollback_job.job_id, lines=80)
            event_text = "\n".join(row.raw_line for row in event_rows)
            self.assertEqual(finished.status, "success")
            self.assertEqual(finished.run_start_sha, later_sha)
            self.assertEqual((repo_root / "a.py").read_text(encoding="utf-8"), 'print("base")\n')
            self.assertTrue(_tracked_clean(repo_root))
            self.assertIn("rolling back newer overlap job-later-overlap", event_text)
            self.assertIn("rolling back source job job-source-chain", event_text)
            self.assertFalse(
                (jobs_root / source_job.job_id / "rollback_scope_manifest.json").exists()
            )
            self.assertFalse(
                (jobs_root / later_job.job_id / "rollback_scope_manifest.json").exists()
            )
            self.assertFalse((jobs_root / rollback_job.job_id / "rollback_request.json").exists())

    async def test_queue_persist_rollback_manifest_writes_db_only_in_db_primary(self) -> None:
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
            queue = async_queue_mod.AsyncJobQueue(
                repo_root=repo_root,
                lock_path=root / "am_patch.lock",
                jobs_root=jobs_root,
                executor=_NoopExecutor(),
                job_db=db,
                patches_root=patches_root,
                target_repo_roots={"patchhub": repo_root},
            )
            job = JobRecord(
                job_id="job-source-db-primary-write",
                created_utc="2026-03-24T10:00:00Z",
                mode="patch",
                issue_id="389",
                commit_summary="Buggy change",
                patch_basename="issue_389_v1.zip",
                raw_command="python3 scripts/am_patch.py 389",
                canonical_command=["python3", "scripts/am_patch.py", "389"],
                status="success",
                effective_runner_target_repo="patchhub",
                run_start_sha=base_sha,
                run_end_sha=source_sha,
            )

            await queue._persist_rollback_manifest(job)

            authority = db.load_rollback_manifest(job.job_id)
            self.assertIsNotNone(authority)
            self.assertEqual(str(authority.get("source_job_id") or ""), job.job_id)
            self.assertFalse((jobs_root / job.job_id / "rollback_scope_manifest.json").exists())
            self.assertIsNone(job.rollback_scope_manifest_rel_path)
            self.assertIsNone(job.rollback_scope_manifest_hash)

    def test_rollback_runtime_db_primary_does_not_fallback_to_request_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_root = root / "patches" / "artifacts" / "web_jobs"
            job = JobRecord(
                job_id="job-rollback-db-primary-no-fallback",
                created_utc="2026-03-24T10:00:00Z",
                mode="rollback",
                issue_id="389",
                commit_summary="Rollback",
                patch_basename=None,
                raw_command="patchhub rollback source",
                canonical_command=["patchhub", "rollback", "source"],
            )
            job_dir = jobs_root / job.job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "rollback_request.json").write_text(
                json.dumps(
                    {
                        "source_job_id": "source-job",
                        "scope_kind": "full",
                        "selected_repo_paths": [],
                        "rollback_preflight_token": "token",
                    },
                    ensure_ascii=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            async def _load_job_record_any(_job_id: str):
                return None

            async def _load_all_jobs():
                return []

            async def _capture_head_sha_for_job(_job: JobRecord):
                return ""

            async def _append_log(_job: JobRecord, _line: str):
                return None

            async def _append_event(_job: JobRecord, _broker, _payload: dict[str, object]):
                return None

            handler = rollback_runtime_mod.build_rollback_job_handler(
                jobs_root=jobs_root,
                load_job_record_any=_load_job_record_any,
                load_all_jobs=_load_all_jobs,
                load_manifest_for_job=lambda _job: None,
                load_request_for_job=lambda _job: None,
                allow_filesystem_request_fallback=False,
                target_repo_roots={},
                capture_head_sha_for_job=_capture_head_sha_for_job,
                append_log=_append_log,
                append_event=_append_event,
            )

            with self.assertRaises(rollback_runtime_mod.RollbackRuntimeError):
                handler._load_request(job)
