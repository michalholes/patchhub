from __future__ import annotations

from pathlib import Path
from typing import Protocol

from am_patch.archive import archive_patch
from am_patch.artifacts import build_artifacts
from am_patch.cli import CliArgs
from am_patch.config import Policy
from am_patch.errors import RunnerError
from am_patch.log import Logger
from am_patch.paths import Paths
from am_patch.post_success_audit import run_post_success_audit
from am_patch.run_result import RunResult, normalize_failure_summary
from am_patch.runtime import parse_gate_list, stage_rank
from am_patch.scope import changed_paths
from am_patch.workspace import delete_workspace, rollback_to_checkpoint


class PostRunContext(Protocol):
    cli: CliArgs
    policy: Policy
    repo_root: Path
    paths: Paths
    log_path: Path
    logger: Logger
    effective_target_repo_name: str | None


def _ctx_effective_target_repo_name(ctx: PostRunContext) -> str | None:
    try:
        return ctx.effective_target_repo_name
    except AttributeError:
        return None


def _resolve_workspace_archive_path(
    *,
    result: RunResult,
    cli: CliArgs,
    repo_root: Path,
    paths: Paths,
    issue_id: str,
    logger: Logger,
    policy: Policy,
) -> Path | None:
    archived_path = result.used_patch_for_zip

    if not policy.patch_script_archive_enabled:
        return archived_path

    if result.exit_code == 0:
        if (
            archived_path is None
            and result.patch_script is not None
            and result.patch_script.exists()
        ):
            archived_path = archive_patch(logger, result.patch_script, paths.successful_dir)
        return archived_path

    patch_source: Path
    try:
        patch_script_arg = cli.patch_script
    except AttributeError:
        patch_script_arg = None

    if result.patch_script is not None:
        patch_source = result.patch_script
    elif patch_script_arg:
        raw = Path(patch_script_arg)
        if raw.is_absolute():
            patch_source = raw
        else:
            repo_candidate = (repo_root / raw).resolve()
            patch_dir_candidate = (paths.patch_dir / raw).resolve()
            patch_source = repo_candidate if repo_candidate.exists() else patch_dir_candidate
    else:
        patch_source = (paths.patch_dir / f"issue_{issue_id}.py").resolve()

    candidates: list[Path] = [patch_source, (paths.patch_dir / patch_source.name).resolve()]

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    for candidate in unique_candidates:
        if candidate.exists():
            return archive_patch(logger, candidate, paths.unsuccessful_dir)

    logger.section("ARCHIVE PATCH")
    logger.line(f"no patch script found to archive; tried: {unique_candidates}")
    return None


def _sorted_unique_paths(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for raw in group:
            path = str(raw).strip().lstrip("/")
            if not path or path in seen:
                continue
            seen.add(path)
            merged.append(path)
    return sorted(merged)


def _resolve_failure_zip_inputs(
    *,
    cli: CliArgs,
    repo_root: Path,
    paths: Paths,
    logger: Logger,
    result: RunResult,
    issue_id: str,
    workspace_deleted_before_audit: bool,
) -> tuple[Path, list[str]]:
    files_for_fail_zip = list(result.files_for_fail_zip)

    if cli.mode == "finalize":
        live_dirty_now: list[str] = []
        if result.exit_code != 0:
            live_dirty_now = changed_paths(logger, repo_root)
        files_for_fail_zip = _sorted_unique_paths(
            files_for_fail_zip,
            list(result.issue_diff_paths),
            live_dirty_now,
        )
        return repo_root, files_for_fail_zip

    if workspace_deleted_before_audit:
        return repo_root, files_for_fail_zip

    if result.ws_for_posthook is not None and result.ws_for_posthook.repo.exists():
        return result.ws_for_posthook.repo, files_for_fail_zip

    workspace_repo = paths.workspaces_dir / f"issue_{issue_id}" / "repo"
    return workspace_repo, files_for_fail_zip


def _maybe_run_success_audit(
    *,
    logger: Logger,
    repo_root: Path,
    policy: Policy,
    result: RunResult,
) -> int:
    if result.exit_code != 0 or result.push_ok_for_posthook is not True:
        return result.exit_code

    try:
        run_post_success_audit(logger, repo_root, policy)
        return result.exit_code
    except Exception as audit_error:
        result.exit_code = 1
        logger.section("AUDIT")
        logger.line(f"post_success_audit_failed={audit_error!r}")
        if isinstance(audit_error, RunnerError):
            stage, reason = normalize_failure_summary(
                error=audit_error,
                primary_fail_stage=result.primary_fail_stage,
                secondary_failures=result.secondary_failures,
                parse_gate_list=parse_gate_list,
                stage_rank=stage_rank,
            )
            result.final_fail_stage = stage
            result.final_fail_reason = reason
        else:
            result.final_fail_stage = "AUDIT"
            result.final_fail_reason = "audit failed"
        return result.exit_code


def run_post_run_pipeline(*, ctx: PostRunContext, result: RunResult) -> int:
    cli = ctx.cli
    policy = ctx.policy
    repo_root = ctx.repo_root
    paths = ctx.paths
    log_path = ctx.log_path
    logger = ctx.logger

    try:
        if cli.mode in ("workspace", "finalize", "finalize_workspace") and not policy.test_mode:
            issue_id = str(cli.issue_id or "unknown")
            archived_path: Path | None = None
            if cli.mode == "workspace":
                archived_path = _resolve_workspace_archive_path(
                    result=result,
                    cli=cli,
                    repo_root=repo_root,
                    paths=paths,
                    issue_id=issue_id,
                    logger=logger,
                    policy=policy,
                )

            run_audit_after_workspace_delete = (
                result.exit_code == 0
                and result.push_ok_for_posthook is True
                and cli.mode in ("workspace", "finalize_workspace")
                and result.delete_workspace_after_archive
                and result.ws_for_posthook is not None
            )
            workspace_deleted_before_audit = False
            if run_audit_after_workspace_delete:
                workspace_for_delete = result.ws_for_posthook
                assert workspace_for_delete is not None
                delete_workspace(logger, workspace_for_delete)
                workspace_deleted_before_audit = True

            _maybe_run_success_audit(
                logger=logger,
                repo_root=repo_root,
                policy=policy,
                result=result,
            )

            ws_repo_for_fail_zip, files_for_fail_zip = _resolve_failure_zip_inputs(
                cli=cli,
                repo_root=repo_root,
                paths=paths,
                logger=logger,
                result=result,
                issue_id=issue_id,
                workspace_deleted_before_audit=workspace_deleted_before_audit,
            )

            if policy.artifact_stage_enabled:
                build_artifacts(
                    logger=logger,
                    cli=cli,
                    policy=policy,
                    paths=paths,
                    repo_root=repo_root,
                    log_path=log_path,
                    exit_code=result.exit_code,
                    unified_mode=result.unified_mode,
                    patch_applied_successfully=result.patch_applied_successfully,
                    archived_patch=archived_path,
                    failed_patch_blobs_for_zip=result.failed_patch_blobs_for_zip,
                    files_for_fail_zip=files_for_fail_zip,
                    ws_repo_for_fail_zip=ws_repo_for_fail_zip,
                    ws_attempt=(
                        result.ws_for_posthook.attempt
                        if result.ws_for_posthook is not None
                        else None
                    ),
                    issue_diff_base_sha=result.issue_diff_base_sha,
                    issue_diff_paths=result.issue_diff_paths,
                    effective_target_repo_name=_ctx_effective_target_repo_name(ctx),
                )
            if (
                result.exit_code != 0
                and result.rollback_ws_for_posthook is not None
                and result.rollback_ckpt_for_posthook is not None
            ):
                mode = policy.rollback_workspace_on_fail
                do_rollback = False
                skip_reason = "non-patch-failure"
                is_patch_failure = result.primary_fail_stage == "PATCH"

                if is_patch_failure:
                    if mode == "always":
                        do_rollback = True
                    elif mode == "none-applied":
                        do_rollback = result.applied_ok_count == 0
                        if not do_rollback:
                            skip_reason = "applied-ok"
                    else:
                        skip_reason = "mode-never"

                if do_rollback:
                    logger.line(
                        f"ROLLBACK: executed (mode={mode} applied_ok={result.applied_ok_count})"
                    )
                    rollback_to_checkpoint(
                        logger,
                        result.rollback_ws_for_posthook.repo,
                        result.rollback_ckpt_for_posthook,
                    )
                else:
                    logger.line(
                        "ROLLBACK: skipped "
                        f"(mode={mode} reason={skip_reason} "
                        f"applied_ok={result.applied_ok_count})"
                    )

            if (
                result.exit_code == 0
                and result.delete_workspace_after_archive
                and result.ws_for_posthook is not None
                and not workspace_deleted_before_audit
            ):
                delete_workspace(logger, result.ws_for_posthook)
    except Exception as posthook_error:
        try:
            logger.section("POSTHOOK-ERROR")
            logger.line(repr(posthook_error))
        except Exception:
            pass

    if cli.mode == "workspace" and policy.test_mode:
        try:
            logger.section("TEST MODE CLEANUP")
            if result.ws_for_posthook is None:
                logger.line("workspace_present=0")
            else:
                logger.line("workspace_present=1")
                logger.line(f"workspace_root={result.ws_for_posthook.root}")
                logger.line("workspace_delete=1")
                delete_workspace(logger, result.ws_for_posthook)
        except Exception as cleanup_error:
            try:
                logger.section("TEST_MODE_CLEANUP_ERROR")
                logger.line(repr(cleanup_error))
            except Exception:
                pass

    return result.exit_code
