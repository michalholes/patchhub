from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .web_jobs_derived import read_effective_applied_files

if TYPE_CHECKING:
    from .web_jobs_db import WebJobsDatabase

_SUMMARY_STOP_RE = re.compile(r"^[A-Z][A-Z_ ]+:\s*")
_ISSUE_DIFF_LINE_RE = re.compile(r"^issue_diff_zip=(.+)$")


def _parse_diff_manifest(data: bytes) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    text = data.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        if not raw.startswith("FILE "):
            continue
        path = raw[5:].strip()
        if not path or path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _parse_final_summary_files(text: str) -> list[str]:
    lines = text.splitlines()
    start_idx = -1
    for idx, raw in enumerate(lines):
        if raw.strip() == "FILES:":
            start_idx = idx + 1
    if start_idx < 0:
        return []

    files: list[str] = []
    seen: set[str] = set()
    started = False
    for raw in lines[start_idx:]:
        line = raw.strip()
        if not line:
            if started:
                continue
            started = True
            continue
        if _SUMMARY_STOP_RE.match(line):
            break
        started = True
        if line in seen:
            continue
        seen.add(line)
        files.append(line)
    return files


def _parse_issue_diff_zip_from_log(text: str) -> str | None:
    match_value: str | None = None
    for raw in text.splitlines():
        match = _ISSUE_DIFF_LINE_RE.match(raw.strip())
        if not match:
            continue
        value = match.group(1).strip()
        if value:
            match_value = value
    return match_value


def _resolve_logged_diff_path(patches_root: Path, raw_path: str) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None

    patches_real = patches_root.resolve()
    candidates: list[Path] = []
    path = Path(raw)
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append((patches_root.parent / path).resolve())
        candidates.append((patches_root / path).resolve())

    for cand in candidates:
        try:
            cand_real = cand.resolve()
            cand_real.relative_to(patches_real)
        except Exception:
            continue
        if cand_real.exists() and cand_real.is_file():
            return cand_real
    return None


def _read_diff_manifest(diff_path: Path) -> list[str]:
    if not diff_path.exists() or not diff_path.is_file():
        return []
    try:
        with zipfile.ZipFile(diff_path, "r") as zf:
            return _parse_diff_manifest(zf.read("manifest.txt"))
    except Exception:
        return []


def derive_applied_files_from_log_text(
    *,
    patches_root: Path,
    log_text: str,
) -> tuple[list[str], str]:
    logged_diff = _parse_issue_diff_zip_from_log(log_text)
    if logged_diff:
        diff_path = _resolve_logged_diff_path(patches_root, logged_diff)
        if diff_path is not None:
            files = _read_diff_manifest(diff_path)
            if files:
                return files, "diff_manifest"

    files = _parse_final_summary_files(log_text)
    if files:
        return files, "final_summary"
    return [], "unavailable"


def collect_job_applied_files(
    *,
    patches_root: Path,
    jobs_root: Path,
    job: Any,
    job_db: WebJobsDatabase | None = None,
) -> tuple[list[str], str]:
    if str(getattr(job, "status", "")) != "success":
        return [], "non_success"

    if job_db is not None:
        return read_effective_applied_files(job_db, str(getattr(job, "job_id", "")))

    log_path = Path(jobs_root) / str(getattr(job, "job_id", "")) / "runner.log"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        log_text = ""
    return derive_applied_files_from_log_text(patches_root=patches_root, log_text=log_text)
