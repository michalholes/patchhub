from __future__ import annotations

import contextlib
import os
import re
import stat as statlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .models import AppStats, RunEntry, StatsWindow

_ANSI_RX = re.compile(r"\x1b\[[0-9;]*m")
# Deterministic in-process cache for historical runs indexing.
# Invalidation is signature-based: (count, max mtime_ns, max size) across matching log files.
_RUNS_CACHE: dict[tuple[str, str], tuple[tuple[int, int, int], list[RunEntry]]] = {}


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_ansi(s: str) -> str:
    return _ANSI_RX.sub("", s)


def parse_run_result_from_log_text(
    text: str,
) -> tuple[Literal["success", "fail", "unknown"], str | None]:
    lines = [strip_ansi(line_text).strip() for line_text in text.splitlines() if line_text.strip()]
    result_line: str | None = None
    for line in reversed(lines[-200:]):
        if line.startswith("RESULT:"):
            result_line = line
            break
    if result_line == "RESULT: SUCCESS":
        return "success", result_line
    if result_line == "RESULT: FAIL":
        return "fail", result_line
    return "unknown", result_line


def _tail_path(log_path: Path, *, tail_suffix: str = ".tail.txt") -> Path:
    # Idempotent: avoid runaway ".tail.txt.tail.txt..." if caller passes a tail file.
    name = log_path.name
    if name.endswith(tail_suffix):
        return log_path
    return log_path.with_name(name + tail_suffix)


def _read_sanitized_tail_text(log_path: Path) -> str | None:
    tail_path = _tail_path(log_path)
    if not tail_path.exists() or not tail_path.is_file():
        return None
    return tail_path.read_text(encoding="utf-8", errors="replace")


def _write_sanitized_tail_text(log_path: Path, text: str) -> None:
    tail_path = _tail_path(log_path)
    tmp_path = tail_path.with_name(tail_path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8", errors="replace")
    tmp_path.replace(tail_path)


def _build_sanitized_tail_from_log(log_path: Path) -> str:
    # Read only the tail of the log (bounded IO) and strip ANSI only for those lines.
    max_bytes = 256 * 1024
    data: bytes
    with log_path.open("rb") as f:
        try:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
        except Exception:
            f.seek(0)
        data = f.read()
    chunk = data.decode("utf-8", errors="replace")
    raw_lines = [ln for ln in chunk.splitlines() if ln.strip()]
    # Keep enough context for RESULT parsing while keeping compute bounded.
    tail_lines = raw_lines[-400:]
    sanitized = [strip_ansi(ln).rstrip() for ln in tail_lines]
    return "\n".join(sanitized) + "\n"


def _ensure_sanitized_tail_text(
    log_path: Path,
    *,
    log_mtime_ns: int | None = None,
) -> str:
    tail_path = _tail_path(log_path)
    if tail_path.exists() and tail_path.is_file():
        try:
            if log_mtime_ns is None:
                log_mtime_ns = log_path.stat().st_mtime_ns
            tail_stat = tail_path.stat()
            if tail_stat.st_mtime_ns >= int(log_mtime_ns):
                return tail_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            # If we cannot compare freshness, fall back to the existing tail.
            with contextlib.suppress(Exception):
                return tail_path.read_text(encoding="utf-8", errors="replace")

    text = _build_sanitized_tail_from_log(log_path)
    # Best-effort cache; indexing must still succeed.
    with contextlib.suppress(Exception):
        _write_sanitized_tail_text(log_path, text)
    return text


def parse_run_result_from_sanitized_text(
    text: str,
) -> tuple[Literal["success", "fail", "unknown"], str | None]:
    # Input is already ANSI-free.
    lines = [line_text.strip() for line_text in text.splitlines() if line_text.strip()]
    result_line: str | None = None
    for line in reversed(lines[-200:]):
        if line.startswith("RESULT:"):
            result_line = line
            break
    if result_line == "RESULT: SUCCESS":
        return "success", result_line
    if result_line == "RESULT: FAIL":
        return "fail", result_line
    return "unknown", result_line


def _scan_matching_logs(
    patches_root: Path,
    rx: re.Pattern[str],
    *,
    collect: bool,
) -> tuple[tuple[int, int, int], list[tuple[Path, int, float, int, int]]]:
    logs_dir = patches_root / "logs"
    try:
        it = os.scandir(logs_dir)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return (0, 0, 0), []

    infos: list[tuple[Path, int, float, int, int]] = []
    count = 0
    max_mtime_ns = 0
    max_size = 0

    with it:
        for ent in it:
            name = ent.name
            if name.endswith(".tail.txt"):
                continue
            m = rx.search(name)
            if not m:
                continue
            try:
                issue_id = int(m.group(1))
            except Exception:
                continue
            try:
                st = ent.stat()
            except Exception:
                continue
            if not statlib.S_ISREG(st.st_mode):
                continue

            count += 1
            if int(st.st_mtime_ns) > max_mtime_ns:
                max_mtime_ns = int(st.st_mtime_ns)
            if int(st.st_size) > max_size:
                max_size = int(st.st_size)

            if collect:
                infos.append(
                    (
                        Path(logs_dir) / name,
                        issue_id,
                        float(st.st_mtime),
                        int(st.st_mtime_ns),
                        int(st.st_size),
                    )
                )

    return (count, max_mtime_ns, max_size), infos


def runs_signature(patches_root: Path, log_filename_regex: str) -> tuple[int, int, int]:
    rx = re.compile(log_filename_regex)
    sig, _infos = _scan_matching_logs(patches_root, rx, collect=False)
    return sig


def _iter_runs_and_sig(
    patches_root: Path,
    log_filename_regex: str,
) -> tuple[tuple[int, int, int], list[RunEntry]]:
    rx = re.compile(log_filename_regex)
    sig, infos = _scan_matching_logs(patches_root, rx, collect=True)

    key = (str(patches_root), log_filename_regex)
    cached = _RUNS_CACHE.get(key)
    if cached is not None:
        cached_sig, cached_runs = cached
        if cached_sig == sig:
            return sig, list(cached_runs)

    runs: list[RunEntry] = []
    for log_path, issue_id, mtime_s, mtime_ns, _size in sorted(infos, key=lambda x: x[0].name):
        tail = _ensure_sanitized_tail_text(log_path, log_mtime_ns=mtime_ns)
        result, result_line = parse_run_result_from_sanitized_text(tail)
        runs.append(
            RunEntry(
                issue_id=issue_id,
                log_rel_path=str(Path("logs") / log_path.name),
                result=result,
                result_line=result_line,
                mtime_utc=_utc_iso(mtime_s),
            )
        )

    runs.sort(key=lambda r: (r.mtime_utc, r.issue_id), reverse=True)
    _RUNS_CACHE[key] = (sig, runs)
    return sig, runs


def iter_runs(patches_root: Path, log_filename_regex: str) -> list[RunEntry]:
    _sig, runs = _iter_runs_and_sig(patches_root, log_filename_regex)
    return runs


def iter_runs_with_signature(
    patches_root: Path,
    log_filename_regex: str,
) -> tuple[tuple[int, int, int], list[RunEntry]]:
    return _iter_runs_and_sig(patches_root, log_filename_regex)


def compute_stats(runs: list[RunEntry], windows_days: list[int]) -> AppStats:
    now = datetime.now(UTC)

    def window(days: int) -> StatsWindow:
        cutoff = now.timestamp() - days * 86400
        filtered = [r for r in runs if _parse_iso(r.mtime_utc) >= cutoff]
        return _count(filtered, days)

    all_time = _count(runs, 0)
    return AppStats(all_time=all_time, windows=[window(d) for d in windows_days])


def _parse_iso(s: str) -> float:
    # s is in Z form
    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return dt.timestamp()


def _count(runs: list[RunEntry], days: int) -> StatsWindow:
    succ = sum(1 for r in runs if r.result == "success")
    fail = sum(1 for r in runs if r.result == "fail")
    unk = sum(1 for r in runs if r.result == "unknown")
    return StatsWindow(days=days, total=len(runs), success=succ, fail=fail, unknown=unk)
