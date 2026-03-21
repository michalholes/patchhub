from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeVar

from .log import Logger, RunResult
from .scope import changed_paths

_T = TypeVar("_T")


class GateStepCallback(Protocol):
    def __call__(
        self,
        *,
        step_key: str,
        pre_dirty: list[str],
        post_dirty: list[str],
    ) -> None: ...


def _step_log_suffix(step_key: str) -> str:
    return str(step_key).strip()


def _step_delta(pre_dirty: list[str], post_dirty: list[str]) -> list[str]:
    pre_set = {p for p in pre_dirty if p}
    return sorted(p for p in post_dirty if p and p not in pre_set)


def capture_gate_step(
    logger: Logger,
    cwd: Path,
    *,
    step_key: str,
    run_step: Callable[[], _T],
    callback: GateStepCallback | None = None,
) -> _T:
    key = _step_log_suffix(step_key)
    pre_dirty = sorted(changed_paths(logger, cwd))
    logger.line(f"gate_step_pre_dirty_{key}={pre_dirty}")
    try:
        result = run_step()
    except BaseException as step_exc:
        step_tb = step_exc.__traceback__
        post_dirty = sorted(changed_paths(logger, cwd))
        logger.line(f"gate_step_post_dirty_{key}={post_dirty}")
        logger.line(f"gate_step_delta_{key}={_step_delta(pre_dirty, post_dirty)}")
        if callback is not None:
            try:
                callback(step_key=key, pre_dirty=pre_dirty, post_dirty=post_dirty)
            except BaseException as callback_exc:
                raise step_exc.with_traceback(step_tb) from callback_exc
        raise
    post_dirty = sorted(changed_paths(logger, cwd))
    logger.line(f"gate_step_post_dirty_{key}={post_dirty}")
    logger.line(f"gate_step_delta_{key}={_step_delta(pre_dirty, post_dirty)}")
    if callback is not None:
        callback(step_key=key, pre_dirty=pre_dirty, post_dirty=post_dirty)
    return result


def run_logged_gate_step(
    logger: Logger,
    cwd: Path,
    *,
    step_key: str,
    argv: list[str],
    callback: GateStepCallback | None = None,
    env: dict[str, str] | None = None,
    failure_dump_mode: str | None = None,
) -> RunResult:
    def _run_step() -> RunResult:
        run_failure_dump_mode = failure_dump_mode
        if env is None and run_failure_dump_mode is None:
            return logger.run_logged(argv, cwd=cwd)
        if env is None:
            assert run_failure_dump_mode is not None
            return logger.run_logged(
                argv,
                cwd=cwd,
                failure_dump_mode=run_failure_dump_mode,
            )
        if run_failure_dump_mode is None:
            return logger.run_logged(
                argv,
                cwd=cwd,
                env=env,
            )
        return logger.run_logged(
            argv,
            cwd=cwd,
            env=env,
            failure_dump_mode=run_failure_dump_mode,
        )

    return capture_gate_step(
        logger,
        cwd,
        step_key=step_key,
        run_step=_run_step,
        callback=callback,
    )
