from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from .models import JobRecord
from .web_jobs_db import WebJobsDatabase
from .web_jobs_legacy_fs import list_legacy_job_jsons, load_legacy_job_record

SyncJobLookup = Callable[[str], JobRecord | None]
AsyncJobLookup = Callable[[str], Awaitable[JobRecord | None]]


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
