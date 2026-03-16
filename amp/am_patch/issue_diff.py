from __future__ import annotations

import contextlib
import os
import re
import zipfile
from pathlib import Path

from .archive import _fsync_dir, _fsync_file, _tmp_path_for_atomic_write, pick_versioned_dest
from .errors import RunnerError
from .git_ops import unified_diff_since
from .log import Logger


def derive_finalize_pseudo_issue_id(*, log_path: Path, finalize_template: str) -> str:
    # finalize_template: "am_patch_finalize_{ts}.log"
    if "{ts}" not in finalize_template:
        raise RunnerError(
            "POSTHOOK",
            "FINALIZE_ID",
            f"invalid finalize log template (missing '{{ts}}'): {finalize_template!r}",
        )

    prefix, suffix = finalize_template.split("{ts}", 1)
    name = log_path.name
    if not name.startswith(prefix) or not name.endswith(suffix):
        raise RunnerError(
            "POSTHOOK",
            "FINALIZE_ID",
            (
                "finalize log name does not match template: "
                f"name={name!r} template={finalize_template!r}"
            ),
        )
    ts = name[len(prefix) : len(name) - len(suffix)]
    if not ts:
        raise RunnerError(
            "POSTHOOK",
            "FINALIZE_ID",
            f"unable to extract ts from finalize log name: {name!r}",
        )
    return f"FINALIZE_{ts}"


def collect_issue_logs(*, logs_dir: Path, issue_id: str, issue_template: str) -> list[Path]:
    # issue_template: "am_patch_issue_{issue}_{ts}.log"
    if "{issue}" not in issue_template or "{ts}" not in issue_template:
        raise RunnerError(
            "POSTHOOK",
            "LOGS",
            f"invalid issue log template (expected '{{issue}}' and '{{ts}}'): {issue_template!r}",
        )

    # Build a deterministic filename regex from the template.
    pat = re.escape(issue_template)
    pat = pat.replace(re.escape("{issue}"), re.escape(issue_id))
    pat = pat.replace(re.escape("{ts}"), r".+")
    rx = re.compile(rf"^{pat}$")

    matches: list[Path] = []
    try:
        for p in logs_dir.iterdir():
            if p.is_file() and rx.match(p.name):
                matches.append(p)
    except FileNotFoundError:
        return []

    matches.sort(key=lambda p: p.name)
    return matches


def _normalize_rel_paths(paths: list[str]) -> list[str]:
    norm: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        p = (raw or "").strip().lstrip("/")
        if not p:
            continue
        if p not in seen:
            seen.add(p)
            norm.append(p)
    norm.sort()
    return norm


def make_issue_diff_zip(
    *,
    logger: Logger,
    repo_root: Path,
    artifacts_dir: Path,
    logs_dir: Path,
    base_sha: str,
    issue_id: str,
    files_to_promote: list[str],
    log_paths: list[Path],
) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dest = artifacts_dir / f"issue_{issue_id}_diff.zip"
    dest = pick_versioned_dest(dest)

    rel_paths = _normalize_rel_paths(files_to_promote)

    diff_entries: list[str] = []
    log_entries: list[str] = []
    snapshot_manifest: list[str] = []
    snapshot_entries = 0

    tmp_path = _tmp_path_for_atomic_write(dest)
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()

    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            # Diffs
            for rel in rel_paths:
                diff = unified_diff_since(logger, repo_root, base_sha, rel)
                if not diff.strip():
                    continue
                patch_name = f"diff/{rel}.patch"
                z.writestr(patch_name, diff.encode("utf-8"))
                diff_entries.append(patch_name)

            # Logs
            logs_sorted = sorted(log_paths, key=lambda p: p.name)
            for p in logs_sorted:
                if not p.exists() or not p.is_file():
                    continue
                z.write(p, arcname=f"logs/{p.name}")
                log_entries.append(f"logs/{p.name}")

            # Full-file snapshots (raw bytes)
            for rel in rel_paths:
                src_path = repo_root / rel
                if src_path.is_file():
                    data = src_path.read_bytes()
                    arcname = f"files/{rel}"
                    z.writestr(arcname, data)
                    snapshot_entries += 1
                    snapshot_manifest.append(f"SNAP {arcname} bytes={len(data)}")
                else:
                    snapshot_manifest.append(f"SNAP_MISSING {rel}")

            # Manifest
            lines: list[str] = []
            lines.append(f"issue_id={issue_id}")
            lines.append(f"base_sha={base_sha}")
            lines.append(f"files_to_promote={len(rel_paths)}")
            for rel in rel_paths:
                lines.append(f"FILE {rel}")
            lines.append(f"diff_entries={len(diff_entries)}")
            for d in sorted(diff_entries):
                lines.append(f"DIFF {d}")
            lines.append(f"logs={len(log_entries)}")
            for log_name in sorted(log_entries):
                lines.append(f"LOG {log_name}")

            lines.append(f"snapshot_entries={snapshot_entries}")
            lines.extend(snapshot_manifest)
            lines.append("")
            z.writestr("manifest.txt", "\n".join(lines).encode("utf-8"))

        _fsync_file(tmp_path)
        os.replace(tmp_path, dest)
        _fsync_dir(dest.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()

    logger.section("ISSUE DIFF BUNDLE")
    logger.line(f"issue_diff_zip={dest}")
    return dest
