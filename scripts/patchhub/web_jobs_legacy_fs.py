from __future__ import annotations

import json
import os
import stat as statlib
from pathlib import Path
from typing import Any

from .models import JobRecord, LegacyJobSnapshot

__all__ = [
    "iter_legacy_job_dirs",
    "legacy_jobs_signature",
    "list_legacy_job_jsons",
    "list_legacy_job_jsons_and_signature",
    "load_legacy_job_json",
    "load_legacy_job_record",
    "read_legacy_job_snapshot",
]

_LIST_CACHE: dict[str, tuple[tuple[int, int], int, list[dict[str, Any]]]] = {}


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _scan_job_dirs_and_names(jobs_root: Path) -> tuple[tuple[int, int], list[str]]:
    try:
        it = os.scandir(jobs_root)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return (0, 0), []

    count = 0
    max_mtime_ns = 0
    names: list[str] = []
    with it:
        for ent in it:
            if not ent.is_dir():
                continue
            names.append(ent.name)
            job_json = jobs_root / ent.name / "job.json"
            try:
                st = job_json.stat()
            except Exception:
                continue
            if not statlib.S_ISREG(st.st_mode):
                continue
            count += 1
            max_mtime_ns = max(max_mtime_ns, int(st.st_mtime_ns))
    names.sort(reverse=True)
    return (count, max_mtime_ns), names


def load_legacy_job_json(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    return _read_json_file(jobs_root / str(job_id) / "job.json")


def load_legacy_job_record(jobs_root: Path, job_id: str) -> JobRecord | None:
    payload = load_legacy_job_json(jobs_root, job_id)
    if payload is None:
        return None
    try:
        return JobRecord.from_json(payload)
    except Exception:
        return None


def legacy_jobs_signature(jobs_root: Path) -> tuple[int, int]:
    sig, _names = _scan_job_dirs_and_names(jobs_root)
    return sig


def list_legacy_job_jsons_and_signature(
    jobs_root: Path,
    *,
    limit: int = 200,
) -> tuple[tuple[int, int], list[dict[str, Any]]]:
    limit = max(1, min(int(limit), 2000))
    key = str(jobs_root.resolve())
    sig, names = _scan_job_dirs_and_names(jobs_root)
    cached = _LIST_CACHE.get(key)
    if cached is not None:
        cached_sig, cached_limit, cached_items = cached
        if cached_sig == sig and limit <= cached_limit:
            return sig, list(cached_items[:limit])

    items: list[dict[str, Any]] = []
    for name in names:
        obj = load_legacy_job_json(jobs_root, name)
        if obj is None:
            continue
        items.append(obj)
        if len(items) >= limit:
            break
    _LIST_CACHE[key] = (sig, limit, items)
    return sig, items


def list_legacy_job_jsons(jobs_root: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    _sig, items = list_legacy_job_jsons_and_signature(jobs_root, limit=limit)
    return items


def read_legacy_job_snapshot(job_dir: Path) -> LegacyJobSnapshot:
    job_json = _read_json_file(job_dir / "job.json")

    log_lines: list[str] = []
    log_path = job_dir / "runner.log"
    if log_path.is_file():
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    event_lines: list[str] = []
    for path in sorted(job_dir.glob("*.jsonl")):
        event_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        break

    return LegacyJobSnapshot(
        job_id=job_dir.name,
        job_json=job_json,
        log_lines=log_lines,
        event_lines=event_lines,
    )


def iter_legacy_job_dirs(jobs_root: Path) -> list[Path]:
    if not jobs_root.is_dir():
        return []
    items = [path for path in jobs_root.iterdir() if path.is_dir()]
    items.sort(key=lambda path: path.name)
    return items
