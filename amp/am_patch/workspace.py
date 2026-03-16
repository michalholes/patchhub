from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RunnerError
from .log import Logger


@dataclass
class Workspace:
    root: Path
    repo: Path
    meta_path: Path
    base_sha: str
    attempt: int
    message: str | None


@dataclass
class WorkspaceCheckpoint:
    kind: str  # 'clean' | 'stash'
    # A git stash reference name (e.g. 'stash@{0}') that represents the pre-patch
    # state (kind='stash').
    stash_ref: str | None = None


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        obj = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {}
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out[str(k)] = v
        return out
    except Exception:
        return {}


def _write_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def open_existing_workspace(
    logger: Logger,
    workspaces_dir: Path,
    issue_id: str,
    *,
    issue_dir_template: str = "issue_{issue}",
    repo_dir_name: str = "repo",
    meta_filename: str = "meta.json",
) -> Workspace:
    ws_root = workspaces_dir / issue_dir_template.format(issue=issue_id)
    repo_dir = ws_root / repo_dir_name
    meta_path = ws_root / meta_filename
    if not repo_dir.exists():
        raise RunnerError("PREFLIGHT", "WORKSPACE", f"workspace not found: {repo_dir}")
    meta = _read_meta(meta_path)
    base_sha = str(meta.get("base_sha", ""))
    attempt = int(meta.get("attempt", 0))
    msg_any = meta.get("message")
    message = msg_any if isinstance(msg_any, str) else None
    return Workspace(
        root=ws_root,
        repo=repo_dir,
        meta_path=meta_path,
        base_sha=base_sha,
        attempt=attempt,
        message=message,
    )


def bump_existing_workspace_attempt(meta_path: Path) -> int:
    meta = _read_meta(meta_path)
    current_any = meta.get("attempt", 0)
    try:
        current = int(current_any)
    except Exception:
        current = 0
    new_attempt = current + 1
    meta["attempt"] = new_attempt
    _write_meta(meta_path, meta)
    return new_attempt


def ensure_workspace(
    logger: Logger,
    workspaces_dir: Path,
    issue_id: str,
    live_repo: Path,
    base_sha: str,
    update: bool,
    soft_reset: bool,
    message: str | None,
    *,
    issue_dir_template: str = "issue_{issue}",
    repo_dir_name: str = "repo",
    meta_filename: str = "meta.json",
    history_logs_dir: str = "logs",
    history_oldlogs_dir: str = "oldlogs",
    history_patches_dir: str = "patches",
    history_oldpatches_dir: str = "oldpatches",
) -> Workspace:
    ws_root = workspaces_dir / issue_dir_template.format(issue=issue_id)
    repo_dir = ws_root / repo_dir_name
    meta_path = ws_root / meta_filename

    # Per-issue history (kept until workspace deletion on successful runs).
    # - logs/: current run log only
    # - oldlogs/: prior run logs
    # - patches/: current run patch script only
    # - oldpatches/: prior run patch scripts
    (ws_root / history_logs_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_oldlogs_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_patches_dir).mkdir(parents=True, exist_ok=True)
    (ws_root / history_oldpatches_dir).mkdir(parents=True, exist_ok=True)

    meta = _read_meta(meta_path)
    attempt = int(meta.get("attempt", 0)) + 1

    if not repo_dir.exists():
        logger.section("WORKSPACE CREATE")
        logger.info_core(f"workspace=create issue={issue_id} base_sha={base_sha}")
        ws_root.mkdir(parents=True, exist_ok=True)
        r = logger.run_logged(["git", "clone", str(live_repo), str(repo_dir)])
        if r.returncode != 0:
            raise RunnerError("PREFLIGHT", "GIT", "git clone failed while creating workspace")
        r2 = logger.run_logged(["git", "checkout", base_sha], cwd=repo_dir)
        if r2.returncode != 0:
            raise RunnerError("PREFLIGHT", "GIT", f"git checkout {base_sha} failed in workspace")

        meta = {"base_sha": base_sha, "attempt": attempt, "message": message}
        _write_meta(meta_path, meta)
    else:
        logger.section("WORKSPACE REUSE")
        logger.info_core(f"workspace=reuse issue={issue_id} base_sha={base_sha}")
        meta.setdefault("message", meta.get("message"))
        persisted = meta.get("base_sha") or base_sha

        if soft_reset:
            r = logger.run_logged(["git", "reset", "--hard", persisted], cwd=repo_dir)
            if r.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace soft reset failed")
            r2 = logger.run_logged(["git", "clean", "-fdx"], cwd=repo_dir)
            if r2.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace clean failed")

        if update:
            r = logger.run_logged(["git", "fetch", "--prune"], cwd=repo_dir)
            if r.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace fetch failed")
            r2 = logger.run_logged(["git", "reset", "--hard", base_sha], cwd=repo_dir)
            if r2.returncode != 0:
                raise RunnerError("PREFLIGHT", "GIT", "workspace update reset failed")
            persisted = base_sha

        meta["base_sha"] = persisted
        meta["attempt"] = attempt
        _write_meta(meta_path, meta)

    meta2 = _read_meta(meta_path)
    return Workspace(
        root=ws_root,
        repo=repo_dir,
        meta_path=meta_path,
        base_sha=str(meta2.get("base_sha", base_sha)),
        attempt=attempt,
        message=meta2.get("message"),
    )


def delete_workspace(logger: Logger, ws: Workspace) -> None:
    logger.section("WORKSPACE DELETE")
    logger.info_core(f"workspace=delete root={ws.root}")
    shutil.rmtree(ws.root, ignore_errors=True)


def create_checkpoint(logger: Logger, repo: Path, *, enabled: bool) -> WorkspaceCheckpoint | None:
    if not enabled:
        logger.section("WORKSPACE CHECKPOINT")
        logger.warning_core("checkpoint=SKIP (disabled)")
        return None

    logger.section("WORKSPACE CHECKPOINT")

    # If workspace is clean, do not create a stash; rollback can restore via reset+clean.
    r0 = logger.run_logged(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo)
    if r0.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to read workspace status for checkpoint")
    if not (r0.stdout or "").strip():
        logger.line("checkpoint=CLEAN (workspace clean; no stash)")
        logger.info_core("checkpoint=CLEAN")
        return WorkspaceCheckpoint(kind="clean")

    # Workspace is dirty: capture complete state including untracked; then immediately
    # re-apply so the user state remains.
    marker = "am_patch_checkpoint"
    r1 = logger.run_logged(["git", "stash", "push", "-u", "-m", marker], cwd=repo)
    if r1.returncode != 0:
        raise RunnerError(
            "PREFLIGHT", "GIT", "failed to create workspace checkpoint (git stash push)"
        )

    # Identify the created stash ref.
    r2 = logger.run_logged(["git", "stash", "list"], cwd=repo)
    if r2.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to list workspace stashes")
    lines = [ln.strip() for ln in (r2.stdout or "").splitlines() if ln.strip()]
    stash_ref: str | None = None
    for ln in lines:
        if marker in ln:
            stash_ref = ln.split(":", 1)[0].strip()
            break
    if not stash_ref:
        raise RunnerError("PREFLIGHT", "GIT", "workspace checkpoint stash not found after creation")

    # Restore state (stash remains for later rollback).
    r3 = logger.run_logged(["git", "stash", "apply", "--index", stash_ref], cwd=repo)
    if r3.returncode != 0:
        raise RunnerError("PREFLIGHT", "GIT", "failed to re-apply workspace checkpoint stash")

    logger.line(f"checkpoint_stash_ref={stash_ref}")
    logger.info_core(f"checkpoint=STASH ref={stash_ref}")
    return WorkspaceCheckpoint(kind="stash", stash_ref=stash_ref)


def drop_checkpoint(logger: Logger, repo: Path, ckpt: WorkspaceCheckpoint | None) -> None:
    if not ckpt:
        return
    if ckpt.kind != "stash" or not ckpt.stash_ref:
        return
    logger.section("WORKSPACE CHECKPOINT DROP")
    _ = logger.run_logged(
        ["git", "stash", "drop", ckpt.stash_ref],
        cwd=repo,
        timeout_hard_fail=False,
    )


def rollback_to_checkpoint(logger: Logger, repo: Path, ckpt: WorkspaceCheckpoint | None) -> None:
    if not ckpt:
        logger.section("WORKSPACE ROLLBACK")
        logger.info_core("rollback=SKIP (no checkpoint)")
        return

    logger.section("WORKSPACE ROLLBACK")
    logger.line(f"rollback_kind={ckpt.kind!r}")
    logger.info_core(f"rollback_kind={ckpt.kind}")

    r1 = logger.run_logged(["git", "reset", "--hard"], cwd=repo)
    if r1.returncode != 0:
        raise RunnerError("ROLLBACK", "GIT", "git reset --hard failed during rollback")
    r2 = logger.run_logged(["git", "clean", "-fd"], cwd=repo)
    if r2.returncode != 0:
        raise RunnerError("ROLLBACK", "GIT", "git clean -fd failed during rollback")
    if ckpt.kind == "stash":
        if not ckpt.stash_ref:
            raise RunnerError("ROLLBACK", "GIT", "missing stash_ref for stash checkpoint")
        logger.line(f"rollback_to={ckpt.stash_ref}")
        r3 = logger.run_logged(["git", "stash", "apply", "--index", ckpt.stash_ref], cwd=repo)
        if r3.returncode != 0:
            raise RunnerError("ROLLBACK", "GIT", "git stash apply failed during rollback")
        _ = logger.run_logged(
            ["git", "stash", "drop", ckpt.stash_ref],
            cwd=repo,
            timeout_hard_fail=False,
        )
    else:
        logger.line("rollback_to=CLEAN (reset+clean only)")
