from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .models import JobRecord
from .rollback_preflight import run_rollback_preflight, validate_source_job_authority


class RollbackHelperActionError(RuntimeError):
    pass


def run_helper_action(
    *,
    action: str,
    jobs_root: Path,
    target_repo_roots: dict[str, Path],
    source_job: JobRecord,
    scope_kind: str,
    selected_repo_paths: list[str],
    all_jobs: list[JobRecord],
) -> dict[str, Any]:
    rel_path, manifest_hash, _kind, _source_ref = validate_source_job_authority(source_job)
    preflight = run_rollback_preflight(
        jobs_root=jobs_root,
        target_repo_roots=target_repo_roots,
        source_job=source_job,
        source_manifest_rel_path=rel_path,
        source_manifest_hash=manifest_hash,
        scope_kind=scope_kind,
        selected_repo_paths=selected_repo_paths,
        all_jobs=all_jobs,
    )
    action_name = str(action or "").strip()
    if action_name in {"", "refresh", "recheck"}:
        return preflight
    repo_root = _resolve_target_root(
        target_repo_roots,
        str(source_job.effective_runner_target_repo or ""),
    )
    if action_name == "discard_dirty":
        paths = list(preflight.get("dirty_overlap_paths") or [])
        if not paths:
            raise RollbackHelperActionError("no overlapping dirty paths to discard")
        _git(repo_root, ["git", "restore", "--staged", "--worktree", "--", *paths])
    elif action_name == "preserve_dirty":
        paths = list(preflight.get("dirty_overlap_paths") or [])
        if not paths:
            raise RollbackHelperActionError("no overlapping dirty paths to preserve")
        _git(
            repo_root,
            [
                "git",
                "stash",
                "push",
                "--include-untracked",
                "-m",
                f"PatchHub rollback preserve {source_job.job_id}",
                "--",
                *paths,
            ],
        )
    elif action_name == "sync_to_authority":
        paths = list(preflight.get("sync_paths") or [])
        head = str(preflight.get("latest_authority_head") or "").strip()
        if not paths or not head:
            raise RollbackHelperActionError("no authority sync work is required")
        _git(
            repo_root,
            ["git", "restore", "--source", head, "--staged", "--worktree", "--", *paths],
        )
        if _has_selected_changes(repo_root, paths):
            _git(
                repo_root,
                ["git", "commit", "-m", f"PatchHub sync rollback scope {source_job.job_id}"],
            )
    else:
        raise RollbackHelperActionError("unsupported rollback helper action")

    return run_rollback_preflight(
        jobs_root=jobs_root,
        target_repo_roots=target_repo_roots,
        source_job=source_job,
        source_manifest_rel_path=rel_path,
        source_manifest_hash=manifest_hash,
        scope_kind=scope_kind,
        selected_repo_paths=selected_repo_paths,
        all_jobs=all_jobs,
    )


def _resolve_target_root(target_repo_roots: dict[str, Path], token: str) -> Path:
    text = str(token or "").strip()
    root = target_repo_roots.get(text)
    if not text or root is None:
        raise RollbackHelperActionError("unknown rollback target repo")
    return Path(root).resolve()


def _has_selected_changes(repo_root: Path, paths: list[str]) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackHelperActionError(_git_error("cannot inspect helper action changes", result))
    return bool(str(result.stdout or "").strip())


def _git(repo_root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackHelperActionError(_git_error("rollback helper action failed", result))
    return result


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> str:
    parts = [str(prefix or "git command failed"), f"rc={int(result.returncode)}"]
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    return "; ".join(parts)
