from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import JobRecord
from .rollback_scope_manifest import (
    entry_display_label,
    load_manifest,
    normalize_selected_entries,
)


class RollbackPreflightError(RuntimeError):
    pass


def run_rollback_preflight(
    *,
    jobs_root: Path,
    target_repo_roots: dict[str, Path],
    source_job: JobRecord,
    source_manifest_rel_path: str,
    source_manifest_hash: str,
    scope_kind: str,
    selected_repo_paths: list[str] | None,
    all_jobs: list[JobRecord],
    load_manifest_for_job: Callable[[JobRecord], dict[str, Any] | None] | None = None,
    allow_filesystem_fallback: bool = True,
) -> dict[str, Any]:
    manifest = _load_authority_manifest(
        jobs_root=jobs_root,
        job=source_job,
        source_manifest_rel_path=source_manifest_rel_path,
        source_manifest_hash=source_manifest_hash,
        load_manifest_for_job=load_manifest_for_job,
        allow_filesystem_fallback=allow_filesystem_fallback,
    )
    selected = normalize_selected_entries(
        manifest,
        scope_kind=scope_kind,
        selected_repo_paths=selected_repo_paths,
    )
    target_token = str(source_job.effective_runner_target_repo or "").strip()
    target_root = _resolve_target_root(target_repo_roots, target_token)
    head_sha = _capture_head_sha(target_root)
    dirty_paths = _dirty_paths(target_root)
    dirty_overlap = sorted(set(dirty_paths).intersection(selected["restore_paths"]))
    dirty_nonoverlap = sorted(set(dirty_paths) - set(dirty_overlap))
    later_jobs = _later_overlap_jobs(
        jobs_root=jobs_root,
        source_job=source_job,
        all_jobs=all_jobs,
        selected_restore_paths=selected["restore_paths"],
        load_manifest_for_job=load_manifest_for_job,
        allow_filesystem_fallback=allow_filesystem_fallback,
    )
    latest_authority = _latest_authority_job(
        all_jobs,
        target_token,
        jobs_root=jobs_root,
        load_manifest_for_job=load_manifest_for_job,
        allow_filesystem_fallback=allow_filesystem_fallback,
    )
    sync_paths = _sync_overlap_paths(
        target_root=target_root,
        latest_authority_job=latest_authority,
        selected_restore_paths=selected["restore_paths"],
    )
    selected_rows = [_entry_summary(item) for item in selected["entries"]]
    chain_rows = [_chain_summary(item) for item in later_jobs]
    can_execute = not dirty_overlap and not sync_paths
    token = _build_token(
        source_job=source_job,
        manifest_hash=source_manifest_hash,
        selected_entry_ids=selected["selected_entry_ids"],
        scope_kind=selected["scope_kind"],
        current_head=head_sha,
        dirty_overlap=dirty_overlap,
        sync_paths=sync_paths,
        chain_job_ids=[str(item["job"].job_id) for item in later_jobs],
    )
    helper_state = _helper_state(
        selected_rows=selected_rows,
        dirty_overlap=dirty_overlap,
        dirty_nonoverlap=dirty_nonoverlap,
        sync_paths=sync_paths,
        chain_rows=chain_rows,
        can_execute=can_execute,
    )
    return {
        "ok": True,
        "source_job_id": str(source_job.job_id),
        "source_issue_id": str(source_job.issue_id or ""),
        "target_repo": target_token,
        "current_head": head_sha,
        "scope_kind": selected["scope_kind"],
        "selected_repo_paths": selected["selected_repo_paths"],
        "restore_paths": selected["restore_paths"],
        "selected_entry_ids": selected["selected_entry_ids"],
        "selected_entries": selected_rows,
        "selected_entry_count": len(selected_rows),
        "manifest_rel_path": source_manifest_rel_path,
        "manifest_hash": source_manifest_hash,
        "dirty_overlap_paths": dirty_overlap,
        "dirty_nonoverlap_paths": dirty_nonoverlap,
        "sync_paths": sync_paths,
        "latest_authority_head": str(
            latest_authority.run_end_sha if latest_authority is not None else ""
        ),
        "chain_steps": chain_rows,
        "chain_required": bool(chain_rows),
        "can_execute": can_execute,
        "rollback_preflight_token": token,
        "helper": helper_state,
    }


def preflight_matches_token(preflight: dict[str, Any], token: str) -> bool:
    return str(preflight.get("rollback_preflight_token") or "") == str(token or "")


def validate_source_job_authority(job: JobRecord) -> tuple[str, str, str, str]:
    rel_path = str(getattr(job, "rollback_scope_manifest_rel_path", "") or "").strip()
    manifest_hash = str(getattr(job, "rollback_scope_manifest_hash", "") or "").strip()
    authority_kind = str(getattr(job, "rollback_authority_kind", "") or "").strip()
    authority_source_ref = str(getattr(job, "rollback_authority_source_ref", "") or "").strip()
    required = [
        str(job.effective_runner_target_repo or "").strip(),
        str(job.run_start_sha or "").strip(),
        str(job.run_end_sha or "").strip(),
        authority_kind,
        authority_source_ref,
    ]
    if not all(required):
        raise RollbackPreflightError("source job is not rollback-capable")
    return rel_path, manifest_hash, authority_kind, authority_source_ref


def load_job_manifest_authority(
    *,
    jobs_root: Path,
    job: JobRecord,
    manifest_loader: Callable[[JobRecord], dict[str, Any] | None] | None,
    allow_filesystem_fallback: bool = True,
) -> dict[str, Any] | None:
    if manifest_loader is not None:
        manifest = manifest_loader(job)
        if isinstance(manifest, dict):
            return manifest
        if not allow_filesystem_fallback:
            return None
    rel_path = str(getattr(job, "rollback_scope_manifest_rel_path", "") or "").strip()
    manifest_hash = str(getattr(job, "rollback_scope_manifest_hash", "") or "").strip()
    if not rel_path or not manifest_hash:
        return None
    try:
        return load_manifest(jobs_root, rel_path, manifest_hash)
    except Exception:
        return None


def _load_authority_manifest(
    *,
    jobs_root: Path,
    job: JobRecord,
    source_manifest_rel_path: str,
    source_manifest_hash: str,
    load_manifest_for_job: Callable[[JobRecord], dict[str, Any] | None] | None,
    allow_filesystem_fallback: bool = True,
) -> dict[str, Any]:
    manifest = load_job_manifest_authority(
        jobs_root=jobs_root,
        job=job,
        manifest_loader=load_manifest_for_job,
        allow_filesystem_fallback=allow_filesystem_fallback,
    )
    if isinstance(manifest, dict):
        return manifest
    if allow_filesystem_fallback and source_manifest_rel_path and source_manifest_hash:
        return load_manifest(jobs_root, source_manifest_rel_path, source_manifest_hash)
    raise RollbackPreflightError("rollback authority payload is missing")


def _job_has_manifest_authority(
    job: JobRecord,
    *,
    jobs_root: Path,
    load_manifest_for_job: Callable[[JobRecord], dict[str, Any] | None] | None,
    allow_filesystem_fallback: bool = True,
) -> bool:
    return (
        load_job_manifest_authority(
            jobs_root=jobs_root,
            job=job,
            manifest_loader=load_manifest_for_job,
            allow_filesystem_fallback=allow_filesystem_fallback,
        )
        is not None
    )


def job_db_manifest_loader(job_db: Any) -> Callable[[JobRecord], dict[str, Any] | None] | None:
    if job_db is None:
        return None
    return lambda job: job_db.load_rollback_manifest(job.job_id)


def _helper_state(
    *,
    selected_rows: list[dict[str, Any]],
    dirty_overlap: list[str],
    dirty_nonoverlap: list[str],
    sync_paths: list[str],
    chain_rows: list[dict[str, Any]],
    can_execute: bool,
) -> dict[str, Any] | None:
    blockers: list[str] = []
    advice: list[str] = []
    actions = ["refresh"]
    if dirty_overlap:
        blockers.append("Overlapping dirty paths block rollback until resolved.")
        actions.extend(["preserve_dirty", "discard_dirty"])
    if dirty_nonoverlap:
        advice.append("Unrelated dirty paths exist, but they do not block this rollback.")
    if sync_paths:
        blockers.append("Live selected scope differs from latest PatchHub authority state.")
        actions.append("sync_to_authority")
    if chain_rows:
        advice.append("Newer overlapping PatchHub jobs will be rolled back first.")
    actions.extend(["scope_narrow", "scope_expand"])
    if can_execute:
        actions.append("execute_rollback")
    if not blockers and not advice:
        return None
    return {
        "open": True,
        "blockers": blockers,
        "advice": advice,
        "actions": actions,
        "selected_entries": selected_rows,
        "chain_steps": chain_rows,
        "dirty_overlap_paths": dirty_overlap,
        "dirty_nonoverlap_paths": dirty_nonoverlap,
        "sync_paths": sync_paths,
    }


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": str(entry.get("entry_id") or ""),
        "lifecycle_kind": str(entry.get("lifecycle_kind") or ""),
        "old_path": str(entry.get("old_path") or ""),
        "new_path": str(entry.get("new_path") or ""),
        "selection_paths": [str(item) for item in list(entry.get("selection_paths") or [])],
        "restore_paths": [str(item) for item in list(entry.get("restore_paths") or [])],
        "label": entry_display_label(entry),
    }


def _chain_summary(item: dict[str, Any]) -> dict[str, Any]:
    job = item["job"]
    return {
        "job_id": str(job.job_id),
        "issue_id": str(job.issue_id or ""),
        "commit_summary": str(job.commit_summary or ""),
        "selected_repo_paths": list(item["selected_repo_paths"]),
        "selected_entry_ids": list(item["selected_entry_ids"]),
    }


def _build_token(
    *,
    source_job: JobRecord,
    manifest_hash: str,
    selected_entry_ids: list[str],
    scope_kind: str,
    current_head: str,
    dirty_overlap: list[str],
    sync_paths: list[str],
    chain_job_ids: list[str],
) -> str:
    payload = {
        "source_job_id": str(source_job.job_id),
        "target_repo": str(source_job.effective_runner_target_repo or ""),
        "manifest_hash": str(manifest_hash or ""),
        "scope_kind": str(scope_kind or ""),
        "selected_entry_ids": list(selected_entry_ids),
        "current_head": str(current_head or ""),
        "dirty_overlap": list(dirty_overlap),
        "sync_paths": list(sync_paths),
        "chain_job_ids": list(chain_job_ids),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_target_root(target_repo_roots: dict[str, Path], token: str) -> Path:
    text = str(token or "").strip()
    root = target_repo_roots.get(text)
    if not text or root is None:
        raise RollbackPreflightError("unknown rollback target repo")
    return Path(root).resolve()


def _capture_head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackPreflightError(_git_error("cannot capture HEAD", result))
    text = str(result.stdout or "").strip()
    if not text:
        raise RollbackPreflightError("cannot capture HEAD")
    return text


def _dirty_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackPreflightError(_git_error("cannot inspect dirty paths", result))
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(result.stdout or "").splitlines():
        line = str(raw or "")
        if len(line) < 4:
            continue
        body = line[3:]
        if " -> " in body:
            old_path, new_path = body.split(" -> ", 1)
            candidates = [old_path.strip(), new_path.strip()]
        else:
            candidates = [body.strip()]
        for path in candidates:
            if path and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _later_overlap_jobs(
    *,
    jobs_root: Path,
    source_job: JobRecord,
    all_jobs: list[JobRecord],
    selected_restore_paths: list[str],
    load_manifest_for_job: Callable[[JobRecord], dict[str, Any] | None] | None,
    allow_filesystem_fallback: bool = True,
) -> list[dict[str, Any]]:
    source_created = int(getattr(source_job, "created_unix_ms", 0) or 0)
    target_token = str(source_job.effective_runner_target_repo or "")
    selected_set = set(selected_restore_paths)
    out: list[dict[str, Any]] = []
    for job in sorted(all_jobs, key=lambda item: int(item.created_unix_ms or 0), reverse=True):
        if str(job.job_id) == str(source_job.job_id):
            continue
        if str(job.status or "") != "success":
            continue
        if str(job.effective_runner_target_repo or "") != target_token:
            continue
        if int(getattr(job, "created_unix_ms", 0) or 0) <= source_created:
            continue
        try:
            manifest = _load_authority_manifest(
                jobs_root=jobs_root,
                job=job,
                source_manifest_rel_path=str(
                    getattr(job, "rollback_scope_manifest_rel_path", "") or ""
                ).strip(),
                source_manifest_hash=str(
                    getattr(job, "rollback_scope_manifest_hash", "") or ""
                ).strip(),
                load_manifest_for_job=load_manifest_for_job,
                allow_filesystem_fallback=allow_filesystem_fallback,
            )
        except Exception:
            continue
        try:
            normalized = normalize_selected_entries(
                manifest,
                scope_kind="full",
                selected_repo_paths=[],
            )
        except Exception:
            continue
        overlap = sorted(selected_set.intersection(normalized["restore_paths"]))
        if not overlap:
            continue
        overlap_selected = normalize_selected_entries(
            manifest,
            scope_kind="subset",
            selected_repo_paths=overlap,
        )
        out.append(
            {
                "job": job,
                "selected_repo_paths": overlap_selected["selected_repo_paths"],
                "selected_entry_ids": overlap_selected["selected_entry_ids"],
            }
        )
    return out


def _latest_authority_job(
    all_jobs: list[JobRecord],
    target_token: str,
    *,
    jobs_root: Path,
    load_manifest_for_job: Callable[[JobRecord], dict[str, Any] | None] | None,
    allow_filesystem_fallback: bool = True,
) -> JobRecord | None:
    items = [
        item
        for item in all_jobs
        if str(item.status or "") == "success"
        and str(item.effective_runner_target_repo or "") == str(target_token or "")
        and _job_has_manifest_authority(
            item,
            jobs_root=jobs_root,
            load_manifest_for_job=load_manifest_for_job,
            allow_filesystem_fallback=allow_filesystem_fallback,
        )
        and str(item.run_end_sha or "").strip()
    ]
    if not items:
        return None
    items.sort(key=lambda item: int(item.created_unix_ms or 0), reverse=True)
    return items[0]


def _sync_overlap_paths(
    *,
    target_root: Path,
    latest_authority_job: JobRecord | None,
    selected_restore_paths: list[str],
) -> list[str]:
    if latest_authority_job is None:
        return []
    current_head = _capture_head_sha(target_root)
    latest_head = str(latest_authority_job.run_end_sha or "").strip()
    if not latest_head or latest_head == current_head:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", "-M", latest_head, current_head],
        cwd=str(target_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackPreflightError(_git_error("cannot inspect live-vs-authority diff", result))
    changed = {
        str(line or "").strip()
        for line in str(result.stdout or "").splitlines()
        if str(line or "").strip()
    }
    return sorted(changed.intersection(set(selected_restore_paths)))


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> str:
    parts = [str(prefix or "git command failed"), f"rc={int(result.returncode)}"]
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    return "; ".join(parts)
