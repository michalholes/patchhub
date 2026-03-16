from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch import git_ops
from am_patch.scope import changed_paths
from am_patch.state import load_state
from am_patch.workspace import create_checkpoint, ensure_workspace


@dataclass
class ExecutionContext:
    ws: Any
    base_sha: str
    state_before: Any
    live_guard_before: str | None
    checkpoint: Any
    changed_before: list[str]


def open_execution_context(
    *,
    logger: Any,
    cli: Any,
    policy: Any,
    paths: Any,
    repo_root: Path,
    patch_script: Path,
    unified_mode: bool,
    files_declared: list[str],
) -> ExecutionContext:
    # Git preflight (live repo)
    git_ops.fetch(logger, repo_root)
    if policy.require_up_to_date and not policy.skip_up_to_date:
        git_ops.require_up_to_date(logger, repo_root, policy.default_branch)
    if policy.enforce_main_branch and not policy.allow_non_main:
        git_ops.require_branch(logger, repo_root, policy.default_branch)

    base_sha = git_ops.head_sha(logger, repo_root)

    logger.section("DECLARED FILES")
    for p in [] if unified_mode else files_declared:
        logger.line(p)

    ws = ensure_workspace(
        logger=logger,
        workspaces_dir=paths.workspaces_dir,
        issue_id=cli.issue_id,
        live_repo=repo_root,
        base_sha=base_sha,
        update=policy.update_workspace,
        soft_reset=policy.soft_reset_workspace,
        message=cli.message,
        issue_dir_template=policy.workspace_issue_dir_template,
        repo_dir_name=policy.workspace_repo_dir_name,
        meta_filename=policy.workspace_meta_filename,
        history_logs_dir=policy.workspace_history_logs_dir,
        history_oldlogs_dir=policy.workspace_history_oldlogs_dir,
        history_patches_dir=policy.workspace_history_patches_dir,
        history_oldpatches_dir=policy.workspace_history_oldpatches_dir,
    )

    logger.section("WORKSPACE META")
    logger.line(f"workspace_root={ws.root}")
    logger.line(f"workspace_repo={ws.repo}")
    logger.line(f"workspace_base_sha={ws.base_sha}")
    logger.line(f"attempt={ws.attempt}")

    st = load_state(ws.root, ws.base_sha)
    logger.section("ISSUE STATE (before)")
    logger.line(f"allowed_union={sorted(st.allowed_union)}")

    live_guard_before: str | None = None
    if policy.live_repo_guard:
        logger.section("LIVE REPO GUARD (before)")
        r = logger.run_logged(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            timeout_stage="SECURITY",
        )
        live_guard_before = r.stdout or ""
        logger.line(f"live_repo_porcelain_len={len(live_guard_before)}")

    ckpt = create_checkpoint(
        logger,
        ws.repo,
        enabled=(policy.rollback_workspace_on_fail != "never"),
    )

    before = changed_paths(logger, ws.repo)

    return ExecutionContext(
        ws=ws,
        base_sha=base_sha,
        state_before=st,
        live_guard_before=live_guard_before,
        checkpoint=ckpt,
        changed_before=before,
    )
