from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from .models import JobRecord
from .web_jobs_db import WebJobsDatabase
from .web_jobs_legacy_fs import list_legacy_job_jsons, load_legacy_job_record

SyncJobLookup = Callable[[str], JobRecord | None]
AsyncJobLookup = Callable[[str], Awaitable[JobRecord | None]]


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _job_json_matches_rollback_candidate(
    payload: dict[str, object],
    *,
    source_job_id: str,
    source_created_unix_ms: int,
    target_repo: str,
    has_manifest_authority: Callable[[str], bool] | None = None,
) -> bool:
    job_id = str(payload.get("job_id", "") or "").strip()
    if not job_id or job_id == source_job_id:
        return False
    if str(payload.get("status", "") or "") != "success":
        return False
    if str(payload.get("effective_runner_target_repo", "") or "") != target_repo:
        return False
    if _payload_int(payload, "created_unix_ms") <= source_created_unix_ms:
        return False
    if has_manifest_authority is not None:
        return has_manifest_authority(job_id)
    manifest_path = str(payload.get("rollback_scope_manifest_rel_path", "") or "").strip()
    manifest_hash = str(payload.get("rollback_scope_manifest_hash", "") or "").strip()
    return bool(manifest_path and manifest_hash)


def _job_record_matches_rollback_candidate(
    job: JobRecord,
    *,
    source_job_id: str,
    source_created_unix_ms: int,
    target_repo: str,
    has_manifest_authority: Callable[[str], bool] | None = None,
) -> bool:
    if str(job.job_id or "") == source_job_id:
        return False
    if str(job.status or "") != "success":
        return False
    if str(job.effective_runner_target_repo or "") != target_repo:
        return False
    if int(getattr(job, "created_unix_ms", 0) or 0) <= source_created_unix_ms:
        return False
    if has_manifest_authority is not None:
        return has_manifest_authority(str(job.job_id or ""))
    manifest_path = str(getattr(job, "rollback_scope_manifest_rel_path", "") or "").strip()
    manifest_hash = str(getattr(job, "rollback_scope_manifest_hash", "") or "").strip()
    return bool(manifest_path and manifest_hash)


def load_job_record_from_persistence(
    *,
    job_id: str,
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
) -> JobRecord | None:
    text = str(job_id or "").strip()
    if not text:
        return None
    if isinstance(job_db, WebJobsDatabase):
        return job_db.load_job_record(text)
    if jobs_root is None:
        return None
    return load_legacy_job_record(Path(jobs_root), text)


async def load_job_record_any_async(
    job_id: str,
    *,
    current_job_lookup: AsyncJobLookup,
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
) -> JobRecord | None:
    text = str(job_id or "").strip()
    if not text:
        return None
    current = await current_job_lookup(text)
    if current is not None:
        return current
    return await asyncio.to_thread(
        load_job_record_from_persistence,
        job_id=text,
        job_db=job_db,
        jobs_root=jobs_root,
    )


def load_job_record_any_sync(
    job_id: str,
    *,
    current_job_lookup: SyncJobLookup,
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
) -> JobRecord | None:
    text = str(job_id or "").strip()
    if not text:
        return None
    current = current_job_lookup(text)
    if current is not None:
        return current
    return load_job_record_from_persistence(
        job_id=text,
        job_db=job_db,
        jobs_root=jobs_root,
    )


def list_job_records_any_sync(
    *,
    current_jobs: Iterable[JobRecord],
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
    limit: int = 5000,
) -> list[JobRecord]:
    mem = list(current_jobs)
    mem_by_id = {str(job.job_id): job for job in mem if str(job.job_id)}
    if isinstance(job_db, WebJobsDatabase):
        disk_raw = job_db.list_job_jsons(limit=limit)
    else:
        disk_raw = [] if jobs_root is None else list_legacy_job_jsons(jobs_root, limit=limit)
    disk: list[JobRecord] = []
    for row in disk_raw:
        job_id = str(row.get("job_id", "")).strip()
        if not job_id or job_id in mem_by_id:
            continue
        job = load_job_record_from_persistence(
            job_id=job_id,
            job_db=job_db,
            jobs_root=jobs_root,
        )
        if job is not None:
            disk.append(job)
    return mem + disk


async def list_job_records_any_async(
    *,
    current_jobs: Iterable[JobRecord],
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
    limit: int = 5000,
) -> list[JobRecord]:
    return await asyncio.to_thread(
        list_job_records_any_sync,
        current_jobs=list(current_jobs),
        job_db=job_db,
        jobs_root=jobs_root,
        limit=limit,
    )


def list_rollback_relevant_job_records_sync(
    *,
    source_job: JobRecord,
    current_jobs: Iterable[JobRecord],
    job_db: WebJobsDatabase | None,
    jobs_root: Path | None,
    limit: int = 5000,
) -> list[JobRecord]:
    source_job_id = str(source_job.job_id or "").strip()
    source_created_unix_ms = int(getattr(source_job, "created_unix_ms", 0) or 0)
    target_repo = str(source_job.effective_runner_target_repo or "").strip()
    out = [source_job]
    seen = {source_job_id} if source_job_id else set()
    has_manifest_authority = (
        job_db.job_has_manifest_authority if isinstance(job_db, WebJobsDatabase) else None
    )
    for job in current_jobs:
        job_id = str(job.job_id or "").strip()
        if not job_id or job_id in seen:
            continue
        if not _job_record_matches_rollback_candidate(
            job,
            source_job_id=source_job_id,
            source_created_unix_ms=source_created_unix_ms,
            target_repo=target_repo,
            has_manifest_authority=has_manifest_authority,
        ):
            continue
        seen.add(job_id)
        out.append(job)
    if isinstance(job_db, WebJobsDatabase):
        disk_raw = job_db.list_rollback_candidate_job_jsons(
            target_repo=target_repo,
            created_after_unix_ms=source_created_unix_ms,
            limit=limit,
        )
    else:
        disk_raw = [] if jobs_root is None else list_legacy_job_jsons(jobs_root, limit=limit)
    for row in disk_raw:
        if not _job_json_matches_rollback_candidate(
            row,
            source_job_id=source_job_id,
            source_created_unix_ms=source_created_unix_ms,
            target_repo=target_repo,
            has_manifest_authority=has_manifest_authority,
        ):
            continue
        job_id = str(row.get("job_id", "") or "").strip()
        if not job_id or job_id in seen:
            continue
        loaded_job = load_job_record_from_persistence(
            job_id=job_id,
            job_db=job_db,
            jobs_root=jobs_root,
        )
        if loaded_job is None:
            continue
        if not _job_record_matches_rollback_candidate(
            loaded_job,
            source_job_id=source_job_id,
            source_created_unix_ms=source_created_unix_ms,
            target_repo=target_repo,
            has_manifest_authority=has_manifest_authority,
        ):
            continue
        seen.add(job_id)
        out.append(loaded_job)
    return out
