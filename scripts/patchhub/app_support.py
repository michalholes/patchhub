from __future__ import annotations

import json
import os
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .models import RunEntry
from .web_jobs_db import WebJobsDatabase
from .web_jobs_legacy_fs import list_legacy_job_jsons


def _json_bytes(obj: Any, status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(obj, ensure_ascii=True, indent=2).encode("utf-8")


def _err(msg: str, status: int = 400) -> tuple[int, bytes]:
    return _json_bytes({"ok": False, "error": msg}, status=status)


def _ok(obj: dict[str, Any] | None = None) -> tuple[int, bytes]:
    out: dict[str, Any] = {"ok": True}
    if obj:
        out.update(obj)
    return _json_bytes(out, status=200)


def _is_ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail_stat_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except Exception:
        return None
    return int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))


def _tail_read_suffix(
    path: Path,
    *,
    max_bytes: int,
    min_newlines: int,
) -> bytes:
    if max_bytes <= 0:
        return b""
    try:
        fp = path.open("rb")
    except Exception:
        return b""
    with fp:
        try:
            fp.seek(0, os.SEEK_END)
            size = int(fp.tell())
        except Exception:
            return b""

        block = 65536
        offset = size
        buf = bytearray()
        newlines = 0

        while offset > 0 and len(buf) < max_bytes and newlines < min_newlines:
            step = min(block, offset, max_bytes - len(buf))
            offset -= step
            try:
                fp.seek(offset, os.SEEK_SET)
                chunk = fp.read(step)
            except Exception:
                break

            if not chunk:
                break

            newlines += chunk.count(b"\n")
            buf[:0] = chunk

        return bytes(buf)


_TAIL_CACHE_TEXT: OrderedDict[tuple[str, int], tuple[tuple[int, int], str]] = OrderedDict()
_TAIL_CACHE_JSONL: OrderedDict[tuple[str, int], tuple[tuple[int, int], list[dict[str, Any]]]] = (
    OrderedDict()
)


def _tail_cache_get_text(
    key: tuple[str, int],
    fp: tuple[int, int],
) -> str | None:
    hit = _TAIL_CACHE_TEXT.get(key)
    if not hit:
        return None
    cached_fp, cached_val = hit
    if cached_fp != fp:
        return None
    return cached_val


def _tail_cache_put_text(
    key: tuple[str, int],
    fp: tuple[int, int],
    val: str,
    *,
    max_entries: int,
) -> None:
    _TAIL_CACHE_TEXT[key] = (fp, val)
    while len(_TAIL_CACHE_TEXT) > max_entries:
        _TAIL_CACHE_TEXT.popitem(last=False)


def _tail_cache_get_jsonl(
    key: tuple[str, int],
    fp: tuple[int, int],
) -> list[dict[str, Any]] | None:
    hit = _TAIL_CACHE_JSONL.get(key)
    if not hit:
        return None
    cached_fp, cached_val = hit
    if cached_fp != fp:
        return None
    return cached_val


def _tail_cache_put_jsonl(
    key: tuple[str, int],
    fp: tuple[int, int],
    val: list[dict[str, Any]],
    *,
    max_entries: int,
) -> None:
    _TAIL_CACHE_JSONL[key] = (fp, val)
    while len(_TAIL_CACHE_JSONL) > max_entries:
        _TAIL_CACHE_JSONL.popitem(last=False)


def read_tail(
    path: Path,
    lines: int,
    *,
    max_bytes: int = 8_388_608,
    cache_max_entries: int = 32,
) -> str:
    if not path.exists():
        return ""
    lines = max(1, min(int(lines), 5000))
    max_bytes = max(0, int(max_bytes))
    cache_max_entries = max(0, int(cache_max_entries))

    fp = _tail_stat_fingerprint(path)
    if fp is None:
        return ""

    key = (str(path), lines)
    if cache_max_entries > 0:
        cached = _tail_cache_get_text(key, fp)
        if cached is not None:
            return cached

    raw = _tail_read_suffix(path, max_bytes=max_bytes, min_newlines=lines + 1)
    if not raw:
        out = ""
    else:
        text = raw.decode("utf-8", errors="replace")
        parts = text.splitlines()
        out = "\n".join(parts[-lines:])

    if cache_max_entries > 0:
        _tail_cache_put_text(key, fp, out, max_entries=cache_max_entries)
    return out


def read_tail_jsonl(
    path: Path,
    lines: int,
    *,
    max_bytes: int = 8_388_608,
    cache_max_entries: int = 32,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = max(1, min(int(lines), 5000))
    max_bytes = max(0, int(max_bytes))
    cache_max_entries = max(0, int(cache_max_entries))

    fp = _tail_stat_fingerprint(path)
    if fp is None:
        return []

    key = (str(path), lines)
    if cache_max_entries > 0:
        cached = _tail_cache_get_jsonl(key, fp)
        if cached is not None:
            return cached

    raw = _tail_read_suffix(path, max_bytes=max_bytes, min_newlines=lines + 1)
    if not raw:
        out: list[dict[str, Any]] = []
    else:
        text = raw.decode("utf-8", errors="replace")
        out = []
        parts = text.splitlines()
        for s in parts[-lines:]:
            s = s.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(cast(dict[str, Any], obj))

    if cache_max_entries > 0:
        _tail_cache_put_jsonl(key, fp, out, max_entries=cache_max_entries)
    return out


def compute_success_archive_rel(
    repo_root: Path, runner_config_toml: Path, patches_root_rel: str
) -> str:
    import subprocess
    import tomllib

    raw = tomllib.loads(runner_config_toml.read_text(encoding="utf-8"))
    name = raw.get("paths", {}).get("success_archive_name")
    if not name:
        name = "{repo}-{branch}.zip"

    repo = repo_root.name
    branch = "main"
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo_root), text=True
        ).strip()
        if out and out != "HEAD":
            branch = out
        else:
            branch = str(raw.get("git", {}).get("default_branch") or "main")
    except Exception:
        branch = str(raw.get("git", {}).get("default_branch") or "main")

    name = name.replace("{repo}", repo).replace("{branch}", branch)
    name = os.path.basename(name)
    if not name.endswith(".zip"):
        name = f"{name}.zip"
    # Return a path relative to patches_root (not repo-root).
    # The caller resolves it under patches_root.
    return name


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ascii_sanitize(s: str) -> str:
    out = []
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def _find_latest_artifact_rel(patches_root: Path, dir_name: str, contains: str) -> str | None:
    d = patches_root / dir_name
    if not d.exists() or not d.is_dir():
        return None
    best = None
    best_m = -1.0
    for p in d.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if contains not in name:
            continue
        try:
            st = p.stat()
        except Exception:
            continue
        if st.st_mtime > best_m:
            best_m = st.st_mtime
            best = name
    if not best:
        return None
    return str(Path(dir_name) / best)


def _decorate_run(
    run: RunEntry,
    *,
    patches_root: Path,
    success_zip_rel: str,
) -> RunEntry:
    try:
        p = patches_root / str(success_zip_rel)
        run.success_zip_rel_path = success_zip_rel if (p.exists() and p.is_file()) else None
    except Exception:
        run.success_zip_rel_path = None
    issue_key = f"issue_{run.issue_id}"

    # Archived patch: try result-specific dir first, then both.
    if run.result == "success":
        run.archived_patch_rel_path = _find_latest_artifact_rel(
            patches_root, "successful", issue_key
        )
    elif run.result in ("fail", "canceled"):
        run.archived_patch_rel_path = _find_latest_artifact_rel(
            patches_root, "unsuccessful", issue_key
        )

    if not run.archived_patch_rel_path:
        run.archived_patch_rel_path = _find_latest_artifact_rel(
            patches_root, "successful", issue_key
        ) or _find_latest_artifact_rel(patches_root, "unsuccessful", issue_key)

    run.diff_bundle_rel_path = _find_latest_artifact_rel(
        patches_root, "artifacts", f"issue_{run.issue_id}_diff"
    )
    return run


def _jobs_source_path(source: WebJobsDatabase | Path) -> WebJobsDatabase | Path:
    if isinstance(source, Path) and source.name != "web_jobs":
        return source / "artifacts" / "web_jobs"
    return source


def active_canceled_runs_source(owner: Any) -> WebJobsDatabase | Path:
    source = getattr(owner, "web_jobs_db", None)
    if isinstance(source, WebJobsDatabase):
        return source
    jobs_root = getattr(owner, "jobs_root", None)
    if isinstance(jobs_root, Path):
        return jobs_root
    patches_root = getattr(owner, "patches_root", None)
    if isinstance(patches_root, Path):
        return patches_root
    raise TypeError("owner must expose web_jobs_db, jobs_root, or patches_root")


def canceled_runs_signature(source: WebJobsDatabase | Path) -> tuple[int, int]:
    source = _jobs_source_path(source)
    if isinstance(source, WebJobsDatabase):
        rows = source.list_job_jsons(limit=1000000)
    else:
        rows = list_legacy_job_jsons(Path(source), limit=1000000)
    canceled = [row for row in rows if str(row.get("status", "")) == "canceled"]
    max_rev = 0
    for row in canceled:
        max_rev = max(max_rev, int(row.get("row_rev", 0) or 0))
    return len(canceled), max_rev


def _iter_canceled_runs(source: WebJobsDatabase | Path) -> list[RunEntry]:
    out: list[RunEntry] = []
    event_name_fn = None
    source = _jobs_source_path(source)
    if isinstance(source, WebJobsDatabase):
        event_name_fn = source.legacy_event_filename
    if isinstance(source, WebJobsDatabase):
        rows = source.list_job_jsons(limit=1000000)
    else:
        rows = list_legacy_job_jsons(Path(source), limit=1000000)
    for raw in rows:
        if str(raw.get("status", "")) != "canceled":
            continue
        issue_s = str(raw.get("issue_id", ""))
        try:
            issue_id = int(issue_s)
        except Exception:
            continue
        if event_name_fn is not None:
            event_name = event_name_fn(str(raw.get("job_id", "")))
        elif issue_s.isdigit():
            event_name = f"am_patch_issue_{issue_s}.jsonl"
        else:
            event_name = "am_patch_finalize.jsonl"
        rel = str(Path("artifacts") / "web_jobs" / str(raw.get("job_id", "")) / event_name)
        mtime_src = str(raw.get("ended_utc") or raw.get("created_utc") or "")
        if mtime_src:
            try:
                mtime = datetime.strptime(mtime_src, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                mtime_utc = _utc_iso(mtime.timestamp())
            except ValueError:
                mtime_utc = mtime_src
        else:
            mtime_utc = ""
        out.append(
            RunEntry(
                issue_id=issue_id,
                log_rel_path=rel,
                result="canceled",
                result_line="RESULT: CANCELED",
                mtime_utc=mtime_utc,
            )
        )
    out.sort(key=lambda r: (r.mtime_utc, r.issue_id), reverse=True)
    return out
