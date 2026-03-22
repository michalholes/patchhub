#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import contextlib
import os
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_read_cfg(cfg_path: Path) -> dict[str, object]:
    try:
        import tomllib

        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _bootstrap_get_arg(argv: list[str], name: str) -> str | None:
    try:
        i = argv.index(name)
    except ValueError:
        return None
    if i + 1 >= len(argv):
        return None
    return argv[i + 1]


def _bootstrap_venv_policy(argv: list[str]) -> tuple[str, str]:
    # Defaults match Policy defaults.
    mode = "auto"
    py_rel = ".venv/bin/python"

    # CLI-only config selection for bootstrap.
    cfg_arg = _bootstrap_get_arg(argv, "--config")
    cfg_path = Path(cfg_arg) if cfg_arg else (_REPO_ROOT / "scripts" / "am_patch" / "am_patch.toml")
    if cfg_path and not cfg_path.is_absolute():
        cfg_path = _REPO_ROOT / cfg_path

    cfg = _bootstrap_read_cfg(cfg_path)
    flat: dict[str, object] = {}
    if isinstance(cfg, dict):
        # Flatten top-level sections into a single mapping (same convention as runner
        # config loader).
        for k, v in cfg.items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    flat[str(kk)] = vv
            else:
                flat[str(k)] = v

    if isinstance(flat.get("venv_bootstrap_mode"), str):
        mode = str(flat["venv_bootstrap_mode"]).strip()
    if isinstance(flat.get("venv_bootstrap_python"), str):
        py_rel = str(flat["venv_bootstrap_python"]).strip() or py_rel

    # CLI overrides for bootstrap only (do not require importing runner modules).
    cli_mode = _bootstrap_get_arg(argv, "--venv-bootstrap-mode")
    if cli_mode:
        mode = cli_mode.strip()
    cli_py = _bootstrap_get_arg(argv, "--venv-bootstrap-python")
    if cli_py:
        py_rel = cli_py.strip() or py_rel

    return mode, py_rel


def _maybe_bootstrap_venv(argv: list[str]) -> None:
    if os.environ.get("AM_PATCH_VENV_BOOTSTRAPPED") == "1":
        return

    mode, py_rel = _bootstrap_venv_policy(argv)
    if mode not in ("auto", "always", "never"):
        # Invalid bootstrap mode: keep legacy behavior to avoid hard failure before config parse.
        mode = "auto"
    if mode == "never":
        return

    venv_py = Path(py_rel)
    venv_py = venv_py if venv_py.is_absolute() else (_REPO_ROOT / venv_py)

    if not venv_py.exists():
        if mode == "always":
            print(
                f"[am_patch_v2] ERROR: venv python not found: {venv_py}",
                file=sys.stderr,
            )
            print(
                "[am_patch_v2] Hint: create venv at repo/.venv and install dev deps "
                "(ruff/pytest/mypy).",
                file=sys.stderr,
            )
            raise SystemExit(2)
        # mode == 'auto': keep running under current interpreter.
        return

    cur = Path(sys.executable).resolve()
    if mode == "always" or ".venv" not in str(cur):
        os.environ["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"
        os.execv(str(venv_py), [str(venv_py), *argv])


_maybe_bootstrap_venv(sys.argv)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from am_patch.config import (
    Policy,
)
from am_patch.engine import (
    build_effective_policy,
    build_paths_and_logger,
    finalize_and_report,
    run_mode,
)
from am_patch.errors import CANCEL_EXIT_CODE, RunnerCancelledError, RunnerError
from am_patch.fs_junk import fs_junk_ignore_partition
from am_patch.log import Logger
from am_patch.patch_archive_select import select_latest_issue_patch
from am_patch.post_success_audit import run_post_success_audit
from am_patch.repo_root import is_under, resolve_repo_root
from am_patch.run_result import RunResult, _normalize_failure_summary
from am_patch.runner_failure_detail import (
    render_runner_error_detail,
    render_runner_error_fingerprint,
)
from am_patch.runtime import _parse_gate_list, _stage_rank

# NOTE: Any change that alters runner behavior MUST bump RUNNER_VERSION and MUST update
# the runner specification under scripts/ (e.g., scripts/am_patch_specification.md).
from am_patch.workspace_history import (
    rotate_current_dir,
    workspace_history_dirs,
    workspace_store_current_log,
    workspace_store_current_patch,
)


def _fs_junk_ignore_partition(
    paths: list[str],
    *,
    ignore_prefixes: tuple[str, ...] | list[str],
    ignore_suffixes: tuple[str, ...] | list[str],
    ignore_contains: tuple[str, ...] | list[str],
) -> tuple[list[str], list[str]]:
    return fs_junk_ignore_partition(
        paths,
        ignore_prefixes=ignore_prefixes,
        ignore_suffixes=ignore_suffixes,
        ignore_contains=ignore_contains,
    )


def _run_post_success_audit(logger: Logger, repo_root: Path, policy: Policy) -> None:
    return run_post_success_audit(logger, repo_root, policy)


def _resolve_repo_root() -> Path:
    return resolve_repo_root()


def _is_under(child: Path, parent: Path) -> bool:
    return is_under(child, parent)


def _select_latest_issue_patch(*, patch_dir: Path, issue_id: str, hint_name: str | None) -> Path:
    return select_latest_issue_patch(patch_dir=patch_dir, issue_id=issue_id, hint_name=hint_name)


def _workspace_history_dirs(
    ws_root: Path,
    *,
    history_logs_dir: str = "logs",
    history_oldlogs_dir: str = "oldlogs",
    history_patches_dir: str = "patches",
    history_oldpatches_dir: str = "oldpatches",
) -> tuple[Path, Path, Path, Path]:
    return workspace_history_dirs(
        ws_root,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )


def _rotate_current_dir(cur_dir: Path, old_dir: Path, prev_attempt: int) -> None:
    return rotate_current_dir(cur_dir, old_dir, prev_attempt)


def _workspace_store_current_patch(
    ws,
    patch_script: Path,
    *,
    history_logs_dir: str,
    history_oldlogs_dir: str,
    history_patches_dir: str,
    history_oldpatches_dir: str,
) -> None:
    return workspace_store_current_patch(
        ws,
        patch_script,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )


def _workspace_store_current_log(
    ws,
    log_path: Path,
    *,
    history_logs_dir: str,
    history_oldlogs_dir: str,
    history_patches_dir: str,
    history_oldpatches_dir: str,
) -> None:
    return workspace_store_current_log(
        ws,
        log_path,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )


def _build_internal_failure_result(exc: Exception) -> RunResult:
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    err = RunnerError("INTERNAL", "INTERNAL", detail)
    return RunResult(
        exit_code=1,
        final_fail_stage="INTERNAL",
        final_fail_reason="unexpected error",
        final_fail_detail=render_runner_error_detail(err),
        final_fail_fingerprint=render_runner_error_fingerprint(err),
    )


def _attach_startup_workspace(ctx, result: RunResult) -> RunResult:
    if getattr(ctx, "preopened_workspace", None) is not None:
        result.ws_for_posthook = ctx.preopened_workspace
    return result


def _build_startup_failure_result(ctx, exc: Exception) -> RunResult:
    if isinstance(exc, RunnerCancelledError):
        return _attach_startup_workspace(
            ctx,
            RunResult(
                exit_code=CANCEL_EXIT_CODE,
                final_fail_stage=exc.stage,
                final_fail_reason="cancel requested",
            ),
        )
    if isinstance(exc, RunnerError):
        final_fail_stage, final_fail_reason = _normalize_failure_summary(
            error=exc,
            primary_fail_stage=None,
            secondary_failures=[],
            parse_gate_list=_parse_gate_list,
            stage_rank=_stage_rank,
        )
        return _attach_startup_workspace(
            ctx,
            RunResult(
                exit_code=1,
                final_fail_stage=final_fail_stage,
                final_fail_reason=final_fail_reason,
                final_fail_detail=render_runner_error_detail(exc),
                final_fail_fingerprint=render_runner_error_fingerprint(exc),
            ),
        )
    return _attach_startup_workspace(ctx, _build_internal_failure_result(exc))


def main(argv: list[str]) -> int:
    res = build_effective_policy(argv)
    if isinstance(res, int):
        return res
    cli, policy, config_path, used_cfg = res
    ctx = None
    exit_code: int | None = None
    try:
        ctx = build_paths_and_logger(cli, policy, config_path, used_cfg)
        startup_failure = getattr(ctx, "startup_failure", None)
        if startup_failure is None:
            try:
                result = run_mode(ctx)
            except Exception as exc:
                result = _build_internal_failure_result(exc)
        else:
            result = _build_startup_failure_result(ctx, startup_failure)
        exit_code = finalize_and_report(ctx, result)
        return exit_code
    finally:
        if ctx is not None and getattr(ctx, "ipc", None) is not None:
            shutdown_handshake_active = False
            with contextlib.suppress(Exception):
                if ctx.ipc.startup_handshake_completed():
                    ctx.logger.emit(
                        severity="DEBUG",
                        channel="DETAIL",
                        message="DEBUG: IPC shutdown handshake waiting for drain_ack\n",
                        kind="TEXT",
                    )

                    def _arm_shutdown_handshake(eos_seq: int) -> None:
                        nonlocal shutdown_handshake_active
                        shutdown_handshake_active = ctx.ipc.begin_shutdown_handshake(
                            eos_seq=eos_seq
                        )

                    ctx.logger.emit_control_event(
                        {"type": "control", "event": "eos"},
                        before_publish=_arm_shutdown_handshake,
                    )
                    if shutdown_handshake_active:
                        ctx.ipc.wait_for_drain_ack()
            if not shutdown_handshake_active:
                delay = (
                    int(getattr(policy, "ipc_socket_cleanup_delay_success_s", 0) or 0)
                    if exit_code == 0
                    else int(getattr(policy, "ipc_socket_cleanup_delay_failure_s", 0) or 0)
                )
                if delay > 0:
                    threading.Event().wait(float(delay))
            with contextlib.suppress(Exception):
                ctx.ipc.stop()
        if ctx is not None:
            with contextlib.suppress(Exception):
                ctx.logger.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
