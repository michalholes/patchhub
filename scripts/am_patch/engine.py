from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from am_patch import git_ops
from am_patch.apply_failure_gates_policy import (
    evaluate_apply_failure_gates_policy_audited,
)
from am_patch.archive import archive_patch
from am_patch.audit_rubric_check import check_audit_rubric_coverage
from am_patch.cli import parse_args
from am_patch.cli_override_normalization import (
    apply_cli_symmetry_helpers,
    build_cli_override_mapping,
)
from am_patch.config import (
    BOOTSTRAP_OWNED_KEYS,
    Policy,
    apply_cli_overrides,
    build_policy,
    filter_policy_layer_cfg,
    policy_for_log,
)
from am_patch.config_file import load_config, resolve_config_path
from am_patch.engine_run_gates import run_finalize_gates
from am_patch.errors import (
    CANCEL_EXIT_CODE,
    RunnerCancelledError,
    RunnerError,
    fingerprint,
)
from am_patch.execution_context import open_execution_context
from am_patch.final_summary import build_terminal_summary, emit_final_summary
from am_patch.lock import FileLock
from am_patch.patch_archive_select import select_latest_issue_patch
from am_patch.patch_exec import run_patch, run_unified_patch_bundle
from am_patch.patch_input import resolve_patch_plan
from am_patch.paths import _workspace_store_current_patch
from am_patch.post_run_pipeline import run_post_run_pipeline
from am_patch.repo_root import is_under
from am_patch.run_result import RunResult, _normalize_failure_summary, build_run_result
from am_patch.runner_failure_detail import (
    render_runner_error_detail,
    render_runner_error_fingerprint,
)
from am_patch.runtime import (
    _gate_progress,
    _parse_gate_list,
    _stage_do,
    _stage_fail,
    _stage_ok,
    _stage_rank,
)
from am_patch.scope import changed_paths, enforce_scope_delta
from am_patch.startup_context import RunContext, build_paths_and_logger
from am_patch.state import save_state, update_union
from am_patch.validation import run_validation
from am_patch.version import RUNNER_VERSION
from am_patch.workspace import drop_checkpoint
from am_patch.workspace_promotion_pipeline import (
    build_allowed_union_promotion_plan,
    complete_workspace_promotion_pipeline,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def _detect_engine_roots(module_file: str | Path | None = None) -> tuple[Path, Path]:
    module_path = Path(module_file) if module_file is not None else Path(__file__)
    package_dir = module_path.resolve().parent
    if package_dir.name != "am_patch":
        raise RunnerError("CONFIG", "INVALID", f"unexpected am_patch package path: {package_dir}")
    import_root = package_dir.parent
    if import_root.name == "scripts" and (import_root / "am_patch").is_dir():
        runner_root = import_root.parent
    else:
        runner_root = import_root
    return runner_root, import_root


def _step_delta(pre_dirty: list[str], post_dirty: list[str]) -> list[str]:
    pre_set = {p for p in pre_dirty if p}
    return sorted(p for p in post_dirty if p and p not in pre_set)


def _legacy_legalized_key(step_key: str) -> str | None:
    if step_key in {"ruff_format", "ruff_fix"}:
        return "legalized_ruff_autofix_files"
    if step_key == "biome_format":
        return "legalized_biome_format_files"
    if step_key == "biome_autofix":
        return "legalized_biome_autofix_files"
    return None


def _under_configured_targets(rel: str, targets: list[str]) -> bool:
    for target in targets:
        item = str(target or "").strip().rstrip("/")
        if item and (rel == item or rel.startswith(item + "/")):
            return True
    return False


def _ruff_step_eligible(policy: Policy, step_key: str, delta: list[str]) -> list[str]:
    if step_key == "ruff_format":
        enabled = bool(policy.ruff_format)
    elif step_key == "ruff_fix":
        enabled = bool(policy.ruff_autofix)
    else:
        return []
    if not enabled or not getattr(policy, "ruff_autofix_legalize_outside", True):
        return []
    return sorted(p for p in delta if _under_configured_targets(p, policy.ruff_targets))


def _biome_step_eligible(policy: Policy, step_key: str, delta: list[str]) -> list[str]:
    if step_key == "biome_format":
        enabled = bool(policy.biome_format)
        legalize_outside = bool(getattr(policy, "biome_format_legalize_outside", True))
    elif step_key == "biome_autofix":
        enabled = bool(policy.biome_autofix)
        legalize_outside = bool(getattr(policy, "biome_autofix_legalize_outside", True))
    else:
        return []
    if not enabled or not legalize_outside:
        return []
    exts = [str(ext).lower() for ext in policy.gate_biome_extensions]
    return sorted(p for p in delta if any(p.lower().endswith(ext) for ext in exts))


def _gate_step_capture_sink(
    *,
    logger: Any,
    policy: Policy,
    workspace_root: Path,
    state: Any,
    files_for_fail_zip: list[str],
    step_key: str,
    pre_dirty: list[str],
    post_dirty: list[str],
) -> tuple[Any, list[str]]:
    delta = _step_delta(pre_dirty, post_dirty)
    if step_key.startswith("ruff_"):
        eligible = _ruff_step_eligible(policy, step_key, delta)
    else:
        eligible = _biome_step_eligible(policy, step_key, delta)
    legalized = sorted(p for p in eligible if p not in state.allowed_union)
    updated_fail_zip = sorted(set(files_for_fail_zip) | set(post_dirty))
    if not legalized:
        logger.line(f"gate_step_legalized_{step_key}={legalized}")
        return state, updated_fail_zip
    next_state = type(state)(
        base_sha=state.base_sha,
        allowed_union=set(state.allowed_union) | set(legalized),
    )
    save_state(workspace_root, next_state)
    logger.line(f"gate_step_legalized_{step_key}={legalized}")
    legacy_key = _legacy_legalized_key(step_key)
    if legacy_key is not None:
        logger.line(f"{legacy_key}={legalized}")
    return next_state, updated_fail_zip


__all__ = [
    "RunContext",
    "build_effective_policy",
    "build_paths_and_logger",
    "run_mode",
    "finalize_and_report",
]


def _is_under(child: Path, parent: Path) -> bool:
    return is_under(child, parent)


def _select_latest_issue_patch(*, patch_dir: Path, issue_id: str, hint_name: str | None) -> Path:
    return select_latest_issue_patch(patch_dir=patch_dir, issue_id=issue_id, hint_name=hint_name)


def build_effective_policy(argv: list[str]) -> int | tuple[Any, Policy, Path, str]:
    cli = parse_args(argv)

    defaults = Policy()
    runner_root, import_root = _detect_engine_roots()
    config_path = resolve_config_path(cli.config_path, runner_root, import_root)
    cfg, used_cfg = load_config(config_path)
    bootstrap_cfg = filter_policy_layer_cfg(cfg, BOOTSTRAP_OWNED_KEYS)
    policy = build_policy(defaults, bootstrap_cfg, source_name="bootstrap_config")

    apply_cli_overrides(policy, build_cli_override_mapping(cli))
    apply_cli_symmetry_helpers(policy, cli)

    if cli.mode == "show_config":
        # Print the same effective config/policy that is normally logged at the start of a run.
        # No workspace, no log file, no side effects.
        print(f"config_path={config_path} used={used_cfg}")
        print(policy_for_log(policy))
        raise SystemExit(0)

    if policy.test_mode and cli.mode != "workspace":
        raise SystemExit("test-mode is supported only in workspace mode")

    return cli, policy, Path(config_path), str(used_cfg)


def run_mode(ctx: RunContext) -> RunResult:
    cli = ctx.cli
    policy = ctx.policy
    repo_root = ctx.repo_root
    runner_root = ctx.runner_root or repo_root
    artifacts_root = ctx.artifacts_root or ctx.patch_root
    patch_root = ctx.patch_root
    patch_dir = ctx.patch_dir
    config_path = ctx.config_path
    used_cfg = ctx.used_cfg
    paths = ctx.paths
    log_path = ctx.log_path
    logger = ctx.logger

    def _result(exit_code: int) -> RunResult:
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

    lock = FileLock(paths.lock_path)
    ctx.lock = lock
    unified_mode: bool = False
    patch_script: Path | None = None
    commit_sha: str | None = None
    push_ok: bool | None = None
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
        logger.section("AM_PATCH START")
        logger.line(f"RUNNER_VERSION={RUNNER_VERSION}")
        logger.line(f"runner_root={runner_root}")
        logger.line(f"artifacts_root={artifacts_root}")
        logger.line(f"live_target_root={ctx.live_target_root}")
        logger.line(f"active_repository_tree_root={ctx.active_repository_tree_root}")
        logger.line(f"active_target_repo_root={repo_root}")
        logger.line(f"repo_root={repo_root}")
        if ctx.effective_target_repo_name is not None:
            logger.line(f"effective_target_repo_name={ctx.effective_target_repo_name}")
        logger.line(f"patch_dir={patch_dir}")
        if patch_dir != patch_root:
            logger.line(f"patch_root={patch_root}")
        logger.line(f"config_path={config_path} used={used_cfg}")
        logger.line(f"log_path={log_path}")
        logger.line(f"symlink_path={paths.symlink_path} -> logs/{log_path.name}")
        logger.section("EFFECTIVE CONFIG")
        logger.line(policy_for_log(policy))

        lock.acquire()

        if cli.mode == "finalize_workspace":
            from .modes.finalize_workspace_mode import run_finalize_workspace_mode

            return run_finalize_workspace_mode(ctx)

        if cli.mode == "finalize":
            git_ops.live_repo_preflight(
                logger,
                repo_root,
                default_branch=policy.default_branch,
                require_up_to_date_flag=policy.require_up_to_date,
                skip_up_to_date=policy.skip_up_to_date,
                enforce_main_branch=policy.enforce_main_branch,
                allow_non_main=policy.allow_non_main,
                auto_pull_if_behind=policy.auto_pull_if_behind,
            )

            issue_diff_base_sha = git_ops.head_sha(logger, repo_root)
            decision_paths_finalize = changed_paths(logger, repo_root)
            issue_diff_paths = list(decision_paths_finalize)

            run_finalize_gates(
                logger=logger,
                repo_root=repo_root,
                decision_paths=decision_paths_finalize,
                policy=policy,
                progress=_gate_progress,
            )

            changed_after_finalize_gates = changed_paths(logger, repo_root)
            issue_diff_paths = sorted(set(issue_diff_paths) | set(changed_after_finalize_gates))

            if policy.commit_and_push:
                commit_sha = git_ops.commit(logger, repo_root, cli.message or "finalize")
                push_ok = git_ops.push(
                    logger,
                    repo_root,
                    policy.default_branch,
                    allow_fail=policy.allow_push_fail,
                )
                final_commit_sha = commit_sha

            logger.section("SUCCESS")
            if policy.commit_and_push:
                logger.line(f"commit_sha={commit_sha}")
                if push_ok is True:
                    logger.line("push=OK")
                else:
                    if policy.allow_push_fail:
                        logger.line("push=FAILED_ALLOWED")
                    else:
                        logger.line("push=FAILED")
            else:
                logger.line("commit_sha=SKIPPED")
                logger.line("push=SKIPPED")

            # Wire finalize results into the unified end-of-run summary.
            push_ok_for_posthook = push_ok
            if push_ok is True and commit_sha:
                try:
                    ns = git_ops.commit_changed_files_name_status(
                        logger,
                        repo_root,
                        commit_sha,
                    )
                    final_pushed_files = [f"{st} {p}" for (st, p) in ns]
                except Exception:
                    # Best-effort only; never override SUCCESS contract.
                    final_pushed_files = None

            return _result(0)

        issue_id = cli.issue_id
        assert issue_id is not None

        plan = ctx.patch_plan
        if plan is None:
            plan = resolve_patch_plan(
                logger=logger,
                cli=cli,
                policy=policy,
                issue_id=issue_id,
                repo_root=repo_root,
                patch_root=patch_root,
            )
        patch_script = plan.patch_script
        unified_mode = plan.unified_mode
        files_current = list(plan.files_declared)

        # Audit rubric guard (future-proofing): fail fast when new audit domains are added
        # but audit/audit_rubric.yaml does not contain the required runtime evidence commands.
        if getattr(policy, "audit_rubric_guard", True):
            missing = check_audit_rubric_coverage(repo_root)
            if missing:
                # Build a deterministic, copy-paste friendly guidance message.
                lines: list[str] = []
                lines.append(
                    "audit rubric guard failed: missing required runtime evidence commands in "
                    "audit/audit_rubric.yaml"
                )
                lines.append("")
                lines.append(
                    "Add these command(s) to audit/audit_rubric.yaml (under "
                    "runtime_evidence.commands, and mark required: true):"
                )
                lines.append("")
                for m in missing:
                    lines.append(
                        f"- domain={m.domain} cli={m.cli_name} caps={','.join(m.capabilities)}"
                    )
                    for c in m.missing_commands:
                        lines.append(f"  - {c} --format yaml")
                lines.append("")
                lines.append("Then re-run runtime evidence to verify:")
                lines.append(
                    "  python3 audit/run_runtime_evidence.py --repo . --rubric "
                    "audit/audit_rubric.yaml"
                )
                raise RunnerError("PREFLIGHT", "CONFIG", "\n".join(lines))

        exec_ctx = open_execution_context(
            logger=logger,
            cli=cli,
            policy=policy,
            paths=paths,
            repo_root=repo_root,
            runner_root=runner_root,
            effective_target_repo_name=str(getattr(ctx, "effective_target_repo_name", "")),
            patch_script=patch_script,
            unified_mode=unified_mode,
            files_declared=files_current,
            preopened_workspace=ctx.preopened_workspace,
        )
        ws = exec_ctx.ws
        ws_for_posthook = ws
        _workspace_store_current_patch(
            ws,
            patch_script,
            history_logs_dir=policy.workspace_history_logs_dir,
            history_oldlogs_dir=policy.workspace_history_oldlogs_dir,
            history_patches_dir=policy.workspace_history_patches_dir,
            history_oldpatches_dir=policy.workspace_history_oldpatches_dir,
        )
        ckpt = exec_ctx.checkpoint
        rollback_ckpt_for_posthook = ckpt
        rollback_ws_for_posthook = ws
        before = exec_ctx.changed_before
        st = exec_ctx.state_before
        live_guard_before = exec_ctx.live_guard_before

        def _capture_sink(*, step_key: str, pre_dirty: list[str], post_dirty: list[str]) -> None:
            nonlocal st, files_for_fail_zip
            st, files_for_fail_zip = _gate_step_capture_sink(
                logger=logger,
                policy=policy,
                workspace_root=ws.root,
                state=st,
                files_for_fail_zip=files_for_fail_zip,
                step_key=step_key,
                pre_dirty=pre_dirty,
                post_dirty=post_dirty,
            )

        try:
            touched_for_zip: list[str] = []
            failed_patch_blobs: list[tuple[str, bytes]] = []
            patch_applied_any = False

            _stage_do("PATCH_APPLY")

            if unified_mode:
                res = run_unified_patch_bundle(
                    logger,
                    patch_script,
                    workspace_repo=ws.repo,
                    policy=policy,
                )
                patch_applied_any = res.applied_ok > 0
                applied_ok_count = res.applied_ok
                files_current = list(res.declared_files)
                touched_for_zip = list(res.touched_files)
                failed_patch_blobs = [(f.name, f.data) for f in res.failures]

                if res.failures:
                    primary_fail_stage = "PATCH"
                    primary_fail_reason = "patch apply failed"

                # For patched.zip on failure: always include touched targets and failed patch blobs.
                # This must be available even if scope enforcement fails later.
                files_for_fail_zip = sorted(set(touched_for_zip) | set(files_current))
                failed_patch_blobs_for_zip = list(failed_patch_blobs)
                patch_applied_successfully = patch_applied_any

            else:
                try:
                    run_patch(logger, patch_script, workspace_repo=ws.repo, policy=policy)
                    patch_applied_any = True
                    applied_ok_count = 1
                except RunnerError as e:
                    primary_fail_stage = "PATCH"
                    primary_fail_reason = e.message
                    patch_applied_any = False

            after = changed_paths(logger, ws.repo)
            if (not unified_mode) and (primary_fail_stage is not None):
                patch_applied_any = set(after) != set(before)
            touched: list[str] = []
            try:
                touched = enforce_scope_delta(
                    logger,
                    files_current=files_current,
                    before=before,
                    after=after,
                    no_op_fail=policy.no_op_fail,
                    allow_no_op=policy.allow_no_op,
                    allow_outside_files=policy.allow_outside_files,
                    allowed_union=st.allowed_union,
                    declared_untouched_fail=policy.declared_untouched_fail,
                    allow_declared_untouched=policy.allow_declared_untouched,
                    blessed_outputs=policy.blessed_gate_outputs,
                    ignore_prefixes=policy.scope_ignore_prefixes,
                    ignore_suffixes=policy.scope_ignore_suffixes,
                    ignore_contains=policy.scope_ignore_contains,
                )
            except RunnerError as _scope_e:
                if primary_fail_stage is None:
                    raise
                logger.section("SECONDARY FAILURE")
                logger.line(str(_scope_e))
                secondary_failures.append((str(_scope_e.stage), str(_scope_e.message)))

            if primary_fail_stage is None:
                _stage_ok("PATCH_APPLY")
            else:
                _stage_fail("PATCH_APPLY")

            # Snapshot dirty paths immediately after patch (before gates).
            dirty_after_patch = list(after)

            # For patched.zip on failure: include the cumulative issue allowed_union plus any known
            # patch targets and current dirty paths. This must be available even if scope
            # enforcement failed (e.g. patch apply failure followed by a scope secondary failure).
            fail_zip_files = set(st.allowed_union)
            fail_zip_files |= set(dirty_after_patch)
            fail_zip_files |= set(files_current)
            fail_zip_files |= set(touched)
            fail_zip_files |= set(touched_for_zip)
            files_for_fail_zip = sorted(fail_zip_files)
            failed_patch_blobs_for_zip = list(failed_patch_blobs)
            patch_applied_successfully = patch_applied_any

        except Exception:
            _stage_fail("PATCH_APPLY")
            raise

        # Live repo guard: after patching (before gates) if scope includes patch.
        if (
            policy.live_repo_guard
            and live_guard_before is not None
            and policy.live_repo_guard_scope == "patch"
        ):
            logger.section("LIVE REPO GUARD (after patch)")
            r2 = logger.run_logged(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=repo_root,
                timeout_stage="SECURITY",
            )
            live_guard_after = r2.stdout or ""
            logger.line(f"live_repo_porcelain_len={len(live_guard_after)}")
            if live_guard_after != live_guard_before:
                raise RunnerError(
                    "SECURITY",
                    "LIVE_REPO_CHANGED",
                    "live repo changed during patching (expected no changes)",
                )

        # Update union AFTER patch success (even if this run was noop with -n).
        st = update_union(st, files_current)
        if policy.allow_outside_files:
            # Spec: -a must also legalize any touched paths into allowed_union for this ISSUE_ID.
            st = update_union(st, touched)
            logger.line(f"legalized_outside_files={sorted(set(touched) - set(files_current))}")
        save_state(ws.root, st)
        logger.section("ISSUE STATE (after)")
        logger.line(f"allowed_union={sorted(st.allowed_union)}")

        defer_patch_apply_failure = False
        if primary_fail_stage is not None:
            if secondary_failures:
                logger.section("SECONDARY FAILURES (summary)")
                for stg, msg in secondary_failures:
                    logger.line(f"{stg}: {msg}")

            should_run_gates, audit_line = evaluate_apply_failure_gates_policy_audited(
                patch_applied_any=patch_applied_any,
                workspace_attempt=ws.attempt,
                partial_policy=policy.apply_failure_partial_gates_policy,
                zero_policy=policy.apply_failure_zero_gates_policy,
            )
            logger.line(audit_line)

            if not should_run_gates:
                raise RunnerError(
                    "PATCH", "PATCH_APPLY", primary_fail_reason or "patch apply failed"
                )

            # Apply failed but gates were explicitly requested by policy.
            # Emit exactly one line (screen-visible only at verbose/debug).
            logger.line("continuing_to_workspace_gates_due_to_patch_apply_failure_policy")
            defer_patch_apply_failure = True

        # Gates in workspace (NO rollback)
        run_validation(
            logger=logger,
            repo_root=repo_root,
            cwd=ws.repo,
            paths=paths,
            policy=policy,
            cli_mode=cli.mode,
            issue_id=cli.issue_id,
            decision_paths=touched,
            progress=_gate_progress,
            gate_step_callback=_capture_sink,
        )

        # Live repo guard: optionally also after gates.
        if (
            policy.live_repo_guard
            and live_guard_before is not None
            and policy.live_repo_guard_scope == "patch_and_gates"
        ):
            logger.section("LIVE REPO GUARD (after gates)")
            r2 = logger.run_logged(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=repo_root,
                timeout_stage="SECURITY",
            )
            live_guard_after = r2.stdout or ""
            logger.line(f"live_repo_porcelain_len={len(live_guard_after)}")
            if live_guard_after != live_guard_before:
                raise RunnerError(
                    "SECURITY",
                    "LIVE_REPO_CHANGED",
                    "live repo changed during patching/gates (expected no changes)",
                )

        if policy.test_mode:
            logger.section("TEST MODE")
            logger.line("TEST_MODE=1")
            logger.line("TEST_MODE_STOP=AFTER_WORKSPACE_GATES_AND_LIVE_GUARD")
            logger.line(
                "STOP: test mode (no promotion, no live gates, no commit/push, no archives)"
            )
            return _result(0)

        # Determine what to promote/commit: all current dirty paths within allowed_union.
        dirty_all = changed_paths(logger, ws.repo)

        if defer_patch_apply_failure:
            # Ensure failure archive includes any gate-induced changes.
            files_for_fail_zip = sorted(set(files_for_fail_zip) | set(dirty_all))
            raise RunnerError("PATCH", "PATCH_APPLY", primary_fail_reason or "patch apply failed")

        promotion_plan = build_allowed_union_promotion_plan(
            logger=logger,
            workspace_base_sha=ws.base_sha,
            dirty_all=dirty_all,
            allowed_union=set(st.allowed_union),
            blessed_outputs=policy.blessed_gate_outputs,
            files_for_fail_zip=files_for_fail_zip,
        )
        files_for_fail_zip = list(promotion_plan.files_for_fail_zip)

        promotion_summary = complete_workspace_promotion_pipeline(
            logger=logger,
            repo_root=repo_root,
            workspace_repo=ws.repo,
            workspace_base_sha=ws.base_sha,
            workspace_message=(ws.message or f"Issue {issue_id}: apply patch"),
            paths=paths,
            policy=policy,
            issue_id=str(issue_id),
            promotion_plan=promotion_plan,
            live_gates_runner=None,
            delete_workspace_after_archive=bool(policy.delete_workspace_on_success),
        )
        issue_diff_base_sha = promotion_summary.issue_diff_base_sha
        issue_diff_paths = list(promotion_summary.issue_diff_paths)
        files_for_fail_zip = list(promotion_summary.files_for_fail_zip)
        push_ok_for_posthook = promotion_summary.push_ok_for_posthook
        final_commit_sha = promotion_summary.final_commit_sha
        final_pushed_files = promotion_summary.final_pushed_files
        delete_workspace_after_archive = promotion_summary.delete_workspace_after_archive

        used_patch_for_zip = None
        if getattr(policy, "patch_script_archive_enabled", True):
            used_patch_for_zip = archive_patch(logger, patch_script, paths.successful_dir)
        drop_checkpoint(logger, ws.repo, ckpt)
        return _result(0)

    except RunnerCancelledError as e:
        logger.section("CANCELED")
        logger.line(str(e))
        logger.line(fingerprint(e))
        final_fail_stage = e.stage
        final_fail_reason = "cancel requested"
        return _result(CANCEL_EXIT_CODE)

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
        return _result(1)


def finalize_and_report(ctx: RunContext, result: RunResult) -> int:
    policy = ctx.policy
    log_path = ctx.log_path
    logger = ctx.logger
    status = ctx.status
    verbosity = ctx.verbosity
    log_level = ctx.log_level
    json_path = ctx.json_path

    lock = result.lock
    exit_code = run_post_run_pipeline(ctx=ctx, result=result)
    final_fail_detail = result.final_fail_detail
    final_fail_fingerprint = result.final_fail_fingerprint
    summary = build_terminal_summary(
        exit_code=exit_code,
        commit_and_push=bool(getattr(policy, "commit_and_push", False)),
        final_commit_sha=result.final_commit_sha,
        final_pushed_files=result.final_pushed_files,
        push_ok_for_posthook=result.push_ok_for_posthook,
        final_fail_stage=result.final_fail_stage,
        final_fail_reason=result.final_fail_reason,
        log_path=log_path,
        json_path=json_path,
        effective_target_repo_name=getattr(ctx, "effective_target_repo_name", None),
    )

    with suppress(Exception):
        status.stop()
    with suppress(Exception):
        if lock is not None:
            lock.release()

    # Final summary must always be present in the log file (even at log_level=quiet).
    screen_quiet = str(verbosity or "").strip().lower() == "quiet"
    log_quiet = str(log_level or "").strip().lower() == "quiet"
    with suppress(Exception):
        logger.emit_json_result(summary=summary)
    emit_final_summary(
        logger=logger,
        summary=summary,
        final_fail_detail=final_fail_detail,
        final_fail_fingerprint=final_fail_fingerprint,
        screen_quiet=screen_quiet,
        log_quiet=log_quiet,
    )

    return exit_code
