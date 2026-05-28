#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _obj_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _bootstrap_read_cfg(cfg_path: Path) -> dict[str, object]:
    try:
        import tomllib

        raw_cfg = cast(object, tomllib.loads(cfg_path.read_text(encoding="utf-8")))
        data = _obj_dict(raw_cfg)
        if data is None:
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
    cfg_path = Path(cfg_arg) if cfg_arg else _REPO_ROOT / "scripts" / "am_patch" / "am_patch.toml"
    if cfg_path and not cfg_path.is_absolute():
        cfg_path = _REPO_ROOT / cfg_path

    cfg = _bootstrap_read_cfg(cfg_path)
    flat: dict[str, object] = {}
    # Flatten top-level sections into a single mapping (same convention as runner
    # config loader).
    for key, value in cfg.items():
        section = _obj_dict(value)
        if section is not None:
            for section_key, section_value in section.items():
                flat[section_key] = section_value
            continue
        flat[key] = value

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
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from am_patch.cli import CliArgs
from am_patch.config import Policy
from am_patch.errors import CANCEL_EXIT_CODE, RunnerCancelledError, RunnerError
from am_patch.run_result import RunResult, normalize_failure_summary
from am_patch.runner_failure_detail import (
    render_runner_error_detail,
    render_runner_error_fingerprint,
)
from am_patch.runtime import parse_gate_list, stage_rank
from am_patch.startup_context import RunContext

BuildEffectivePolicy = Callable[[list[str]], int | tuple[CliArgs, Policy, Path, str]]
BuildPathsAndLogger = Callable[[CliArgs, Policy, Path, str], RunContext]
FinalizeAndReport = Callable[[RunContext, RunResult], int]
RunMode = Callable[[RunContext], RunResult]


class _EngineModule(Protocol):
    build_effective_policy: BuildEffectivePolicy
    build_paths_and_logger: BuildPathsAndLogger
    finalize_and_report: FinalizeAndReport
    run_mode: RunMode


_engine = cast(_EngineModule, importlib.import_module("am_patch.engine"))
build_effective_policy = _engine.build_effective_policy
build_paths_and_logger = _engine.build_paths_and_logger
finalize_and_report = _engine.finalize_and_report
run_mode = _engine.run_mode

# NOTE: Any change that alters runner behavior MUST bump RUNNER_VERSION and MUST update
# the runner specification under scripts/ (e.g., scripts/am_patch_specification.md).


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


def _attach_startup_workspace(ctx: RunContext, result: RunResult) -> RunResult:
    try:
        preopened_workspace = ctx.preopened_workspace
    except AttributeError:
        return result
    if preopened_workspace is not None:
        result.ws_for_posthook = preopened_workspace
    return result


def _build_startup_failure_result(ctx: RunContext, exc: Exception) -> RunResult:
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
        final_fail_stage, final_fail_reason = normalize_failure_summary(
            error=exc,
            primary_fail_stage=None,
            secondary_failures=[],
            parse_gate_list=parse_gate_list,
            stage_rank=stage_rank,
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


def _cleanup_isolated_test_mode_patch_dir(ctx: RunContext) -> None:
    try:
        policy = ctx.policy
    except AttributeError:
        return
    if not bool(policy.test_mode):
        return
    try:
        isolated_work_patch_dir = ctx.isolated_work_patch_dir
    except AttributeError:
        return
    if isolated_work_patch_dir is None:
        return
    if "_test_mode" not in isolated_work_patch_dir.parts:
        return
    with contextlib.suppress(Exception):
        shutil.rmtree(isolated_work_patch_dir, ignore_errors=True)


def main(argv: list[str]) -> int:
    res = build_effective_policy(argv)
    if isinstance(res, int):
        return res
    cli, policy, config_path, used_cfg = res
    ctx: RunContext | None = None
    exit_code: int | None = None
    try:
        ctx = build_paths_and_logger(cli, policy, config_path, used_cfg)
        try:
            startup_failure = ctx.startup_failure
        except AttributeError:
            startup_failure = None
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
        ipc = None if ctx is None else ctx.ipc
        if ctx is not None and ipc is not None:
            shutdown_handshake_active = False
            with contextlib.suppress(Exception):
                if ipc.startup_handshake_completed():
                    ctx.logger.emit(
                        severity="DEBUG",
                        channel="DETAIL",
                        message="DEBUG: IPC shutdown handshake waiting for drain_ack\n",
                        kind="TEXT",
                    )

                    def _arm_shutdown_handshake(eos_seq: int) -> None:
                        nonlocal shutdown_handshake_active
                        shutdown_handshake_active = ipc.begin_shutdown_handshake(eos_seq=eos_seq)

                    ctx.logger.emit_control_event(
                        {"type": "control", "event": "eos"},
                        before_publish=_arm_shutdown_handshake,
                    )
                    if shutdown_handshake_active:
                        ipc.wait_for_drain_ack()
            if not shutdown_handshake_active:
                if exit_code == 0:
                    delay = int(policy.ipc_socket_cleanup_delay_success_s or 0)
                else:
                    delay = int(policy.ipc_socket_cleanup_delay_failure_s or 0)
                if delay > 0:
                    threading.Event().wait(float(delay))
            with contextlib.suppress(Exception):
                ipc.stop()
        if ctx is not None:
            _cleanup_isolated_test_mode_patch_dir(ctx)
            with contextlib.suppress(Exception):
                ctx.logger.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
