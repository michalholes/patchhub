# ruff: noqa: E402
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.job_record_lookup import list_rollback_relevant_job_records_sync
from patchhub.models import JobRecord
from patchhub.rollback_preflight import (
    RollbackPreflightError,
    run_rollback_preflight,
    validate_source_job_authority,
)
from patchhub.rollback_scope_manifest import build_manifest_for_job, write_manifest
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config


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


def _persist_job_with_manifest(
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


def test_latest_source_job_does_not_hydrate_older_jobs() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repo_root = root / "repo"
        jobs_root = root / "patches" / "artifacts" / "web_jobs"
        _init_repo(repo_root)
        (repo_root / "tracked.txt").write_text("base\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Base")
        base_sha = _head_sha(repo_root)
        (repo_root / "tracked.txt").write_text("older\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Older")
        older_sha = _head_sha(repo_root)
        (repo_root / "tracked.txt").write_text("latest\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Latest")
        latest_sha = _head_sha(repo_root)
        db = WebJobsDatabase(load_web_jobs_db_config(repo_root, root / "patches"))
        older = _persist_job_with_manifest(
            repo_root=repo_root,
            jobs_root=jobs_root,
            db=db,
            job=JobRecord(
                job_id="job-older-390",
                created_utc="2026-03-24T10:00:00Z",
                mode="patch",
                issue_id="390",
                commit_summary="Older job",
                patch_basename="issue_390_v1.zip",
                raw_command="python3 scripts/am_patch.py 390",
                canonical_command=["python3", "scripts/am_patch.py", "390"],
                status="success",
                effective_runner_target_repo="patchhub",
                run_start_sha=base_sha,
                run_end_sha=older_sha,
            ),
        )
        source_job = _persist_job_with_manifest(
            repo_root=repo_root,
            jobs_root=jobs_root,
            db=db,
            job=JobRecord(
                job_id="job-latest-390",
                created_utc="2026-03-24T10:10:00Z",
                mode="patch",
                issue_id="390",
                commit_summary="Latest job",
                patch_basename="issue_390_v1.zip",
                raw_command="python3 scripts/am_patch.py 390",
                canonical_command=["python3", "scripts/am_patch.py", "390"],
                status="success",
                effective_runner_target_repo="patchhub",
                run_start_sha=older_sha,
                run_end_sha=latest_sha,
            ),
        )
        loaded_ids: list[str] = []

        def _counting_loader(
            *,
            job_id: str,
            job_db: WebJobsDatabase | None,
            jobs_root: Path | None,
        ):
            del jobs_root
            loaded_ids.append(str(job_id))
            return None if job_db is None else job_db.load_job_record(job_id)

        with patch(
            "patchhub.job_record_lookup.load_job_record_from_persistence",
            side_effect=_counting_loader,
        ):
            jobs = list_rollback_relevant_job_records_sync(
                source_job=source_job,
                current_jobs=[],
                job_db=db,
                jobs_root=jobs_root,
            )

        assert [job.job_id for job in jobs] == [source_job.job_id]
        assert loaded_ids == []
        assert older.job_id not in loaded_ids


def test_optimized_job_corpus_keeps_newer_overlap_chain_detection() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repo_root = root / "repo"
        jobs_root = root / "patches" / "artifacts" / "web_jobs"
        _init_repo(repo_root)
        (repo_root / "tracked.txt").write_text("base\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Base")
        base_sha = _head_sha(repo_root)
        (repo_root / "tracked.txt").write_text("source\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Source")
        source_sha = _head_sha(repo_root)
        (repo_root / "tracked.txt").write_text("newer\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Newer")
        newer_sha = _head_sha(repo_root)
        db = WebJobsDatabase(load_web_jobs_db_config(repo_root, root / "patches"))
        source_job = _persist_job_with_manifest(
            repo_root=repo_root,
            jobs_root=jobs_root,
            db=db,
            job=JobRecord(
                job_id="job-source-390",
                created_utc="2026-03-24T10:00:00Z",
                mode="patch",
                issue_id="390",
                commit_summary="Source job",
                patch_basename="issue_390_v1.zip",
                raw_command="python3 scripts/am_patch.py 390",
                canonical_command=["python3", "scripts/am_patch.py", "390"],
                status="success",
                effective_runner_target_repo="patchhub",
                run_start_sha=base_sha,
                run_end_sha=source_sha,
            ),
        )
        newer_job = _persist_job_with_manifest(
            repo_root=repo_root,
            jobs_root=jobs_root,
            db=db,
            job=JobRecord(
                job_id="job-newer-390",
                created_utc="2026-03-24T10:05:00Z",
                mode="patch",
                issue_id="390",
                commit_summary="Newer overlap",
                patch_basename="issue_390_v2.zip",
                raw_command="python3 scripts/am_patch.py 390",
                canonical_command=["python3", "scripts/am_patch.py", "390"],
                status="success",
                effective_runner_target_repo="patchhub",
                run_start_sha=source_sha,
                run_end_sha=newer_sha,
            ),
        )
        assert not (jobs_root / source_job.job_id / "rollback_scope_manifest.json").exists()
        assert not (jobs_root / newer_job.job_id / "rollback_scope_manifest.json").exists()
        rel_path, manifest_hash, _kind, _ref = validate_source_job_authority(source_job)
        jobs = list_rollback_relevant_job_records_sync(
            source_job=source_job,
            current_jobs=[],
            job_db=db,
            jobs_root=jobs_root,
        )
        preflight = run_rollback_preflight(
            jobs_root=jobs_root,
            target_repo_roots={"patchhub": repo_root},
            source_job=source_job,
            source_manifest_rel_path=rel_path,
            source_manifest_hash=manifest_hash,
            scope_kind="full",
            selected_repo_paths=[],
            all_jobs=jobs,
            load_manifest_for_job=lambda job: db.load_rollback_manifest(job.job_id),
        )

        assert [job.job_id for job in jobs] == [source_job.job_id, newer_job.job_id]
        assert preflight["chain_required"] is True
        assert [item["job_id"] for item in preflight["helper"]["chain_steps"]] == [newer_job.job_id]
        assert preflight["helper"]["open"] is True


def test_run_rollback_preflight_db_primary_does_not_fallback_to_manifest_file() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        repo_root = root / "repo"
        jobs_root = root / "patches" / "artifacts" / "web_jobs"
        _init_repo(repo_root)
        (repo_root / "tracked.txt").write_text("base\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Base")
        base_sha = _head_sha(repo_root)
        (repo_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        _git(repo_root, "add", "tracked.txt")
        _git(repo_root, "commit", "-m", "Change")
        changed_sha = _head_sha(repo_root)

        manifest = build_manifest_for_job(
            repo_root=repo_root,
            source_job_id="job-source-file-only",
            issue_id="390",
            selected_target_repo_token="patchhub",
            effective_runner_target_repo="patchhub",
            run_start_sha=base_sha,
            run_end_sha=changed_sha,
            authority_kind="github",
            authority_source_ref="issue:390",
        )
        rel_path, manifest_hash = write_manifest(jobs_root / "job-source-file-only", manifest)
        source_job = JobRecord(
            job_id="job-source-file-only",
            created_utc="2026-03-24T10:10:00Z",
            mode="patch",
            issue_id="390",
            commit_summary="Change",
            patch_basename="issue_390_v1.zip",
            raw_command="python3 scripts/am_patch.py 390",
            canonical_command=["python3", "scripts/am_patch.py", "390"],
            status="success",
            effective_runner_target_repo="patchhub",
            run_start_sha=base_sha,
            run_end_sha=changed_sha,
            rollback_scope_manifest_rel_path=rel_path,
            rollback_scope_manifest_hash=manifest_hash,
            rollback_authority_kind="github",
            rollback_authority_source_ref="issue:390",
        )

        with pytest.raises(RollbackPreflightError, match="rollback authority payload is missing"):
            run_rollback_preflight(
                jobs_root=jobs_root,
                target_repo_roots={"patchhub": repo_root},
                source_job=source_job,
                source_manifest_rel_path=rel_path,
                source_manifest_hash=manifest_hash,
                scope_kind="full",
                selected_repo_paths=[],
                all_jobs=[source_job],
                load_manifest_for_job=lambda job: None,
                allow_filesystem_fallback=False,
            )
