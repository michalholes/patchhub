from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .web_jobs_legacy_fs import list_legacy_job_jsons


def find_existing_issue_ids(patches_root: Path, default_regex: str) -> set[int]:
    rx = re.compile(default_regex)
    ids: set[int] = set()

    for rel in ["logs", "artifacts", "successful", "unsuccessful"]:
        p = patches_root / rel
        if not p.exists():
            continue
        for item in p.rglob("*"):
            m = rx.search(str(item))
            if not m:
                continue
            try:
                ids.add(int(m.group(1)))
            except (ValueError, IndexError):
                continue

    return ids


def _max_issue_id_from_web_jobs_db(patches_root: Path) -> int | None:
    db_path = patches_root / "artifacts" / "web_jobs.sqlite3"
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT MAX(issue_id_int) FROM web_jobs").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    value = row[0]
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _max_issue_id_from_legacy_jobs(patches_root: Path) -> int | None:
    jobs_root = patches_root / "artifacts" / "web_jobs"
    if not jobs_root.is_dir():
        return None
    max_issue: int | None = None
    for payload in list_legacy_job_jsons(jobs_root, limit=2000):
        raw = str(payload.get("issue_id", "") or "").strip()
        if not raw.isdigit():
            continue
        value = int(raw)
        if value <= 0:
            continue
        max_issue = value if max_issue is None else max(max_issue, value)
    return max_issue


def allocate_next_issue_id(
    patches_root: Path,
    default_regex: str,
    allocation_start: int,
    allocation_max: int,
) -> int:
    existing = find_existing_issue_ids(patches_root, default_regex)
    maxima = [max(existing)] if existing else []
    persisted_db = _max_issue_id_from_web_jobs_db(patches_root)
    if persisted_db is not None:
        maxima.append(persisted_db)
    persisted_legacy = _max_issue_id_from_legacy_jobs(patches_root)
    if persisted_legacy is not None:
        maxima.append(persisted_legacy)
    cur = (max(maxima) + 1) if maxima else allocation_start
    if cur < allocation_start:
        cur = allocation_start
    if cur > allocation_max:
        raise ValueError("Issue allocation exceeded allocation_max")
    return cur
