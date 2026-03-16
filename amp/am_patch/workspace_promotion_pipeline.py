from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch import git_ops
from am_patch.errors import RunnerError
from am_patch.failure_zip import cleanup_on_success_commit as cleanup_failure_zips_on_success
from am_patch.paths import _fs_junk_ignore_partition
from am_patch.promote import promote_files
from am_patch.scope import blessed_gate_outputs_in


@dataclass(frozen=True)
class WorkspacePromotionPlan:
    files_to_promote: list[str]
    issue_diff_base_sha: str
    issue_diff_paths: list[str]
    files_for_fail_zip: list[str]


@dataclass(frozen=True)
class WorkspacePromotionSummary:
    issue_diff_base_sha: str
    issue_diff_paths: list[str]
    files_for_fail_zip: list[str]
    push_ok_for_posthook: bool | None
    final_commit_sha: str | None
    final_pushed_files: list[str] | None
    delete_workspace_after_archive: bool


def build_allowed_union_promotion_plan(
    *,
    logger: Any,
    workspace_base_sha: str,
    dirty_all: list[str],
    allowed_union: set[str],
    blessed_outputs: list[str] | tuple[str, ...],
    files_for_fail_zip: list[str],
) -> WorkspacePromotionPlan:
    dirty_allowed = [path for path in dirty_all if path in allowed_union]
    dirty_blessed = blessed_gate_outputs_in(dirty_all, blessed_outputs=blessed_outputs)

    files_to_promote: list[str] = []
    seen: set[str] = set()
    for path in dirty_allowed + dirty_blessed:
        if path in seen:
            continue
        seen.add(path)
        files_to_promote.append(path)

    logger.section("PROMOTION PLAN")
    logger.line(f"dirty_all={dirty_all}")
    logger.line(f"dirty_allowed={dirty_allowed}")
    logger.line(f"dirty_blessed={dirty_blessed}")
    logger.line(f"files_to_promote={files_to_promote}")

    return WorkspacePromotionPlan(
        files_to_promote=files_to_promote,
        issue_diff_base_sha=workspace_base_sha,
        issue_diff_paths=list(files_to_promote),
        files_for_fail_zip=sorted(set(files_for_fail_zip) | set(dirty_all)),
    )


def build_workspace_delta_promotion_plan(
    *,
    logger: Any,
    workspace_base_sha: str,
    changed_all: list[str],
    files_for_fail_zip: list[str],
    ignore_prefixes: list[str] | tuple[str, ...],
    ignore_suffixes: list[str] | tuple[str, ...],
    ignore_contains: list[str] | tuple[str, ...],
) -> WorkspacePromotionPlan:
    files_to_promote, ignored_paths = _fs_junk_ignore_partition(
        changed_all,
        ignore_prefixes=ignore_prefixes,
        ignore_suffixes=ignore_suffixes,
        ignore_contains=ignore_contains,
    )
    logger.section("PROMOTION PLAN")
    logger.line(f"changed_all={changed_all}")
    logger.line(f"ignored_paths={ignored_paths}")
    logger.line(f"files_to_promote={files_to_promote}")

    if not files_to_promote:
        raise RunnerError("PREFLIGHT", "WORKSPACE", "no promotable workspace changes")

    return WorkspacePromotionPlan(
        files_to_promote=files_to_promote,
        issue_diff_base_sha=workspace_base_sha,
        issue_diff_paths=list(files_to_promote),
        files_for_fail_zip=sorted(set(files_for_fail_zip) | set(files_to_promote)),
    )


def complete_workspace_promotion_pipeline(
    *,
    logger: Any,
    repo_root: Path,
    workspace_repo: Path,
    workspace_base_sha: str,
    workspace_message: str,
    paths: Any,
    policy: Any,
    issue_id: str | None,
    promotion_plan: WorkspacePromotionPlan,
    badguys_runner: Any,
    live_gates_runner: Any | None,
    delete_workspace_after_archive: bool,
) -> WorkspacePromotionSummary:
    promote_files(
        logger=logger,
        workspace_repo=workspace_repo,
        live_repo=repo_root,
        base_sha=workspace_base_sha,
        files_to_promote=promotion_plan.files_to_promote,
        fail_if_live_changed=policy.fail_if_live_files_changed,
        live_changed_resolution=policy.live_changed_resolution,
    )

    decision_paths_live = list(promotion_plan.files_to_promote)
    if live_gates_runner is not None:
        live_gates_runner(decision_paths_live)
    badguys_runner(cwd=repo_root, decision_paths=decision_paths_live)

    commit_sha: str | None = None
    push_ok: bool | None = None
    final_pushed_files: list[str] | None = None

    if policy.commit_and_push:
        commit_sha = git_ops.commit(
            logger,
            repo_root,
            workspace_message,
            stage_all=False,
        )
        push_ok = git_ops.push(
            logger,
            repo_root,
            policy.default_branch,
            allow_fail=policy.allow_push_fail,
        )

        if commit_sha and issue_id is not None:
            cleanup_failure_zips_on_success(
                patch_dir=paths.patch_dir,
                policy=policy,
                issue=str(issue_id),
            )

        if push_ok is True and commit_sha:
            try:
                name_status = git_ops.commit_changed_files_name_status(
                    logger,
                    repo_root,
                    commit_sha,
                )
                final_pushed_files = [f"{status} {path}" for (status, path) in name_status]
            except Exception:
                final_pushed_files = None

    logger.section("SUCCESS")
    if policy.commit_and_push:
        logger.line(f"commit_sha={commit_sha}")
        if push_ok is True:
            logger.line("push=OK")
        elif push_ok is False:
            if policy.allow_push_fail:
                logger.line("push=FAILED_ALLOWED")
            else:
                logger.line("push=FAILED")
        else:
            logger.line("push=UNKNOWN")
    else:
        logger.line("commit_sha=SKIPPED")
        logger.line("push=SKIPPED")

    return WorkspacePromotionSummary(
        issue_diff_base_sha=promotion_plan.issue_diff_base_sha,
        issue_diff_paths=list(promotion_plan.issue_diff_paths),
        files_for_fail_zip=list(promotion_plan.files_for_fail_zip),
        push_ok_for_posthook=push_ok,
        final_commit_sha=commit_sha,
        final_pushed_files=final_pushed_files,
        delete_workspace_after_archive=delete_workspace_after_archive,
    )
