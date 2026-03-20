from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Any

from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    ZipTargetConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
    read_target_repo_from_zip_path,
    zip_contains_patch_file,
)


@dataclass(frozen=True)
class PatchMetadata:
    derived_issue: str | None
    derived_commit_message: str | None
    derived_target_repo: str | None
    zip_commit_used: bool = False
    zip_commit_err: str | None = None
    zip_issue_used: bool = False
    zip_issue_err: str | None = None
    zip_target_err: str | None = None


@dataclass(frozen=True)
class _PatchInventoryRecord:
    stored_rel_path: str
    filename: str
    kind: str
    source_bucket: str
    mtime_ns: int
    mtime_utc: str
    metadata: PatchMetadata


@dataclass(frozen=True)
class _ScanRoot:
    source_bucket: str
    rel_under_patches_root: str


def _patches_root_prefix(cfg: Any) -> str:
    return str(cfg.paths.patches_root or "patches").replace("\\", "/").rstrip("/")


def _rel_under_patches_root(cfg: Any, raw_value: str) -> str | None:
    value = str(raw_value or "").strip().replace("\\", "/").lstrip("/")
    prefix = _patches_root_prefix(cfg)
    if not prefix:
        return None
    if value == prefix:
        return ""
    if value.startswith(prefix + "/"):
        return value[len(prefix) + 1 :]
    return None


def _stored_rel_path(cfg: Any, rel_under_root: str, filename: str) -> str:
    del cfg
    if rel_under_root:
        return f"{rel_under_root}/{filename}"
    return filename


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_filename_metadata(cfg: Any, filename: str) -> tuple[str | None, str | None]:
    if not cfg.autofill.derive_enabled:
        return None, None

    import re

    try:
        issue_re = re.compile(cfg.autofill.issue_regex)
    except re.error:
        issue_re = None
    try:
        msg_re = re.compile(cfg.autofill.commit_regex)
    except re.error:
        msg_re = None

    issue_id: str | None = None
    if issue_re is not None:
        match = issue_re.search(filename)
        if match and match.groups():
            issue_id = str(match.group(1))

    commit_msg: str | None = None
    if msg_re is not None:
        match = msg_re.match(filename)
        if match and match.groups():
            commit_msg = str(match.group(1))

    if commit_msg is None:
        default_commit = str(cfg.autofill.commit_default_if_no_match or "")
        if default_commit == "basename_no_ext":
            commit_msg = os.path.splitext(filename)[0]

    if commit_msg is not None:
        from .app_support import _ascii_sanitize

        if cfg.autofill.commit_replace_underscores:
            commit_msg = commit_msg.replace("_", " ")
        if cfg.autofill.commit_replace_dashes:
            commit_msg = commit_msg.replace("-", " ")
        if cfg.autofill.commit_collapse_spaces:
            commit_msg = " ".join(commit_msg.split())
        if cfg.autofill.commit_trim:
            commit_msg = commit_msg.strip()
        if cfg.autofill.commit_ascii_only:
            commit_msg = _ascii_sanitize(commit_msg)
            if cfg.autofill.commit_collapse_spaces:
                commit_msg = " ".join(commit_msg.split())
            if cfg.autofill.commit_trim:
                commit_msg = commit_msg.strip()
        if commit_msg == "":
            commit_msg = None

    if issue_id is None:
        default_issue = str(cfg.autofill.issue_default_if_no_match or "")
        issue_id = default_issue if default_issue else None

    return issue_id, commit_msg


def _zip_commit_cfg(cfg: Any) -> ZipCommitConfig:
    return ZipCommitConfig(
        enabled=True,
        filename=cfg.autofill.zip_commit_filename,
        max_bytes=cfg.autofill.zip_commit_max_bytes,
        max_ratio=cfg.autofill.zip_commit_max_ratio,
    )


def _zip_issue_cfg(cfg: Any) -> ZipIssueConfig:
    return ZipIssueConfig(
        enabled=True,
        filename=cfg.autofill.zip_issue_filename,
        max_bytes=cfg.autofill.zip_issue_max_bytes,
        max_ratio=cfg.autofill.zip_issue_max_ratio,
    )


def _zip_target_cfg() -> ZipTargetConfig:
    return ZipTargetConfig(
        enabled=True,
        filename="target.txt",
        max_bytes=128,
        max_ratio=200,
    )


def derive_patch_metadata(core: Any, *, filename: str, path: Path) -> PatchMetadata:
    issue_id, commit_msg = derive_filename_metadata(core.cfg, filename)
    target_repo: str | None = None
    zip_commit_used = False
    zip_commit_err: str | None = None
    zip_issue_used = False
    zip_issue_err: str | None = None
    zip_target_err: str | None = None

    if path.suffix.lower() == ".zip" and core.cfg.autofill.zip_commit_enabled:
        zip_commit, zip_commit_err = read_commit_message_from_zip_path(
            path,
            _zip_commit_cfg(core.cfg),
        )
        if zip_commit is not None:
            commit_msg = zip_commit
            zip_commit_used = True
    if path.suffix.lower() == ".zip" and core.cfg.autofill.zip_issue_enabled:
        zip_issue, zip_issue_err = read_issue_number_from_zip_path(
            path,
            _zip_issue_cfg(core.cfg),
        )
        if zip_issue is not None:
            issue_id = zip_issue
            zip_issue_used = True
    if path.suffix.lower() == ".zip":
        target_repo, zip_target_err = read_target_repo_from_zip_path(path, _zip_target_cfg())

    return PatchMetadata(
        derived_issue=issue_id,
        derived_commit_message=commit_msg,
        derived_target_repo=target_repo,
        zip_commit_used=zip_commit_used,
        zip_commit_err=zip_commit_err,
        zip_issue_used=zip_issue_used,
        zip_issue_err=zip_issue_err,
        zip_target_err=zip_target_err,
    )


def _scan_roots(core: Any) -> list[_ScanRoot]:
    out = [_ScanRoot(source_bucket="patches_root", rel_under_patches_root="")]
    upload_dir = str(getattr(core.cfg.paths, "upload_dir", "") or "")
    upload_rel = _rel_under_patches_root(core.cfg, upload_dir)
    if upload_rel is None or upload_rel == "":
        return out
    out.append(_ScanRoot(source_bucket="upload_dir", rel_under_patches_root=upload_rel))
    return out


def _candidate_kind(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".patch":
        return "patch"
    if suffix == ".diff":
        return "diff"
    if suffix == ".zip":
        ok, _reason = zip_contains_patch_file(path)
        return "zip" if ok else None
    return None


def build_patch_inventory(core: Any) -> tuple[str, list[dict[str, Any]]]:
    rows: list[_PatchInventoryRecord] = []
    seen_paths: set[str] = set()

    for scan_root in _scan_roots(core):
        try:
            abs_root = core.jail.resolve_rel(scan_root.rel_under_patches_root)
        except Exception:
            continue
        try:
            it = os.scandir(abs_root)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        with it:
            entries = sorted(it, key=lambda entry: entry.name)
        for entry in entries:
            try:
                if not entry.is_file():
                    continue
            except Exception:
                continue
            path = Path(entry.path)
            kind = _candidate_kind(path)
            if kind is None:
                continue
            stored_rel_path = _stored_rel_path(
                core.cfg,
                scan_root.rel_under_patches_root,
                entry.name,
            )
            if stored_rel_path in seen_paths:
                continue
            seen_paths.add(stored_rel_path)
            try:
                stat = entry.stat()
            except Exception:
                continue
            mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            metadata = derive_patch_metadata(core, filename=entry.name, path=path)
            rows.append(
                _PatchInventoryRecord(
                    stored_rel_path=stored_rel_path,
                    filename=entry.name,
                    kind=kind,
                    source_bucket=scan_root.source_bucket,
                    mtime_ns=mtime_ns,
                    mtime_utc=_utc_iso(float(stat.st_mtime)),
                    metadata=metadata,
                )
            )

    rows.sort(key=lambda row: (-row.mtime_ns, row.stored_rel_path))

    sig_parts = [
        "|".join(
            [
                row.stored_rel_path,
                row.filename,
                row.kind,
                row.source_bucket,
                str(row.mtime_ns),
                row.metadata.derived_issue or "",
                row.metadata.derived_commit_message or "",
                row.metadata.derived_target_repo or "",
            ]
        )
        for row in rows
    ]
    sig = "patches:" + sha1("\n".join(sig_parts).encode("utf-8")).hexdigest()

    items = [
        {
            "stored_rel_path": row.stored_rel_path,
            "filename": row.filename,
            "kind": row.kind,
            "source_bucket": row.source_bucket,
            "mtime_utc": row.mtime_utc,
            "derived_issue": row.metadata.derived_issue,
            "derived_commit_message": row.metadata.derived_commit_message,
            "derived_target_repo": row.metadata.derived_target_repo,
        }
        for row in rows
    ]
    return sig, items
