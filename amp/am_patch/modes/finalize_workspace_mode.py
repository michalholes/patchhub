from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from am_patch.errors import RunnerError
from am_patch.gates_policy_wiring import run_policy_gates
from am_patch.run_result import RunResult, _normalize_failure_summary, build_run_result
from am_patch.runner_failure_detail import (
    render_runner_error_detail,
    render_runner_error_fingerprint,
)
from am_patch.runtime import _gate_progress, _maybe_run_badguys, _parse_gate_list, _stage_rank
from am_patch.scope import changed_paths
from am_patch.workspace import bump_existing_workspace_attempt, open_existing_workspace
from am_patch.workspace_promotion_pipeline import (
    build_workspace_delta_promotion_plan,
    complete_workspace_promotion_pipeline,
)

if TYPE_CHECKING:
    from am_patch.engine import RunContext


def run_finalize_workspace_mode(ctx: RunContext) -> RunResult:
    cli = ctx.cli
    policy = ctx.policy
    repo_root = ctx.repo_root
    paths = ctx.paths
    logger = ctx.logger

    lock = getattr(ctx, "lock", None)

    unified_mode: bool = False
    patch_script: Path | None = None
    used_patch_for_zip: Path | None = None
    files_for_fail_zip: list[str] = []
    failed_patch_blobs_for_zip: list[tuple[str, bytes]] = []
    patch_applied_successfully: bool = False
    applied_ok_count: int = 0
    rollback_ckpt_for_posthook = None
    rollback_ws_for_posthook = None
    issue_diff_base_sha: str | None = None
    issue_diff_paths: list[str] = []
    delete_workspace_after_archive: bool = False
    ws_for_posthook = None
    push_ok_for_posthook: bool | None = None
    final_commit_sha: str | None = None
    final_pushed_files: list[str] | None = None
    final_fail_stage: str | None = None
    final_fail_reason: str | None = None
    final_fail_detail: str | None = None
    final_fail_fingerprint: str | None = None
    primary_fail_stage: str | None = None
    primary_fail_reason: str | None = None
    secondary_failures: list[tuple[str, str]] = []

    try:
        issue_id = cli.issue_id
        assert issue_id is not None

        ws = open_existing_workspace(
            logger,
            paths.workspaces_dir,
            str(issue_id),
            issue_dir_template=policy.workspace_issue_dir_template,
            repo_dir_name=policy.workspace_repo_dir_name,
            meta_filename=policy.workspace_meta_filename,
        )
        ws_for_posthook = ws

        # Ensure {attempt} increments on each finalize-workspace run.
        ws.attempt = bump_existing_workspace_attempt(ws.meta_path)

        logger.section("FINALIZE WORKSPACE")
        logger.line(f"workspace_root={ws.root}")
        logger.line(f"workspace_repo={ws.repo}")
        logger.line(f"workspace_meta={ws.meta_path}")
        logger.line(f"workspace_base_sha={ws.base_sha}")
        logger.line(f"workspace_attempt={ws.attempt}")

        # Commit message is always sourced from workspace meta.json.
        if not ws.message or not str(ws.message).strip():
            raise RunnerError(
                "PREFLIGHT",
                "WORKSPACE",
                "workspace meta.json missing non-empty message",
            )

        decision_paths_ws = changed_paths(logger, ws.repo)

        # Failure archive hint: include current workspace changes (even in -w) so
        # patched.zip is reproducible if gates fail.
        files_for_fail_zip = sorted(set(files_for_fail_zip) | set(decision_paths_ws))
        run_policy_gates(
            logger=logger,
            cwd=ws.repo,
            repo_root=repo_root,
            policy=policy,
            decision_paths=decision_paths_ws,
            progress=_gate_progress,
        )

        # Gates can modify files (e.g. ruff format/autofix). Refresh the failure
        # archive subset after workspace gates.
        changed_after_ws_gates = changed_paths(logger, ws.repo)
        files_for_fail_zip = sorted(set(files_for_fail_zip) | set(changed_after_ws_gates))

        _maybe_run_badguys(cwd=ws.repo, decision_paths=decision_paths_ws)

        promotion_plan = build_workspace_delta_promotion_plan(
            logger=logger,
            workspace_base_sha=ws.base_sha,
            changed_all=changed_paths(logger, ws.repo),
            files_for_fail_zip=files_for_fail_zip,
            ignore_prefixes=policy.scope_ignore_prefixes,
            ignore_suffixes=policy.scope_ignore_suffixes,
            ignore_contains=policy.scope_ignore_contains,
        )

        promotion_summary = complete_workspace_promotion_pipeline(
            logger=logger,
            repo_root=repo_root,
            workspace_repo=ws.repo,
            workspace_base_sha=ws.base_sha,
            workspace_message=str(ws.message),
            paths=paths,
            policy=policy,
            issue_id=str(cli.issue_id) if cli.issue_id is not None else None,
            promotion_plan=promotion_plan,
            badguys_runner=_maybe_run_badguys,
            live_gates_runner=lambda decision_paths: run_policy_gates(
                logger=logger,
                cwd=repo_root,
                repo_root=repo_root,
                policy=policy,
                decision_paths=decision_paths,
                progress=_gate_progress,
            ),
            delete_workspace_after_archive=bool(
                policy.delete_workspace_on_success and policy.commit_and_push
            ),
        )
        issue_diff_base_sha = promotion_summary.issue_diff_base_sha
        issue_diff_paths = list(promotion_summary.issue_diff_paths)
        files_for_fail_zip = list(promotion_summary.files_for_fail_zip)
        push_ok_for_posthook = promotion_summary.push_ok_for_posthook
        final_commit_sha = promotion_summary.final_commit_sha
        final_pushed_files = promotion_summary.final_pushed_files
        delete_workspace_after_archive = promotion_summary.delete_workspace_after_archive

        if policy.delete_workspace_on_success and not policy.commit_and_push:
            logger.line("workspace_delete=SKIPPED (disable-promotion)")

        exit_code = 0
    except RunnerError as e:
        logger.section("FAILURE")
        logger.line(str(e))
        final_fail_detail = render_runner_error_detail(e)
        final_fail_fingerprint = render_runner_error_fingerprint(e)
        final_fail_stage, final_fail_reason = _normalize_failure_summary(
            error=e,
            primary_fail_stage=primary_fail_stage,
            secondary_failures=secondary_failures,
            parse_gate_list=_parse_gate_list,
            stage_rank=_stage_rank,
        )
        exit_code = 1

    return build_run_result(
        lock=lock,
        exit_code=exit_code,
        unified_mode=unified_mode,
        patch_script=patch_script,
        used_patch_for_zip=used_patch_for_zip,
        files_for_fail_zip=files_for_fail_zip,
        failed_patch_blobs_for_zip=failed_patch_blobs_for_zip,
        patch_applied_successfully=patch_applied_successfully,
        applied_ok_count=applied_ok_count,
        rollback_ckpt_for_posthook=rollback_ckpt_for_posthook,
        rollback_ws_for_posthook=rollback_ws_for_posthook,
        issue_diff_base_sha=issue_diff_base_sha,
        issue_diff_paths=issue_diff_paths,
        delete_workspace_after_archive=delete_workspace_after_archive,
        ws_for_posthook=ws_for_posthook,
        push_ok_for_posthook=push_ok_for_posthook,
        final_commit_sha=final_commit_sha,
        final_pushed_files=final_pushed_files,
        final_fail_stage=final_fail_stage,
        final_fail_reason=final_fail_reason,
        final_fail_detail=final_fail_detail,
        final_fail_fingerprint=final_fail_fingerprint,
        primary_fail_stage=primary_fail_stage,
        primary_fail_reason=primary_fail_reason,
        secondary_failures=secondary_failures,
    )
