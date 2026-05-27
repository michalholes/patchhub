from __future__ import annotations

from typing import Protocol, cast

# NOTE: This module contains helpers extracted from scripts/am_patch.py:main().
# Behavior must remain identical. These helpers intentionally rely on runtime-
# bound globals (status/logger/policy/etc) which are set by the caller.


class _StatusLike(Protocol):
    def break_line(self) -> None: ...

    def set_stage(self, stage: str) -> None: ...


class _LoggerLike(Protocol):
    def emit(
        self,
        *,
        severity: str,
        channel: str,
        message: str,
        kind: str | None = None,
    ) -> None: ...


status: object | None = None
logger: object | None = None
policy: object | None = None
repo_root: object | None = None
paths: object | None = None
cli: object | None = None
run_badguys: object | None = None
RunnerError: object | None = None


def _status_runtime() -> _StatusLike:
    if status is None:
        raise RuntimeError("runtime.status is not initialized")
    return cast(_StatusLike, status)


def _logger_runtime() -> _LoggerLike:
    if logger is None:
        raise RuntimeError("runtime.logger is not initialized")
    return cast(_LoggerLike, logger)


def _emit_core(*, severity: str, line: str, kind: str | None = None) -> None:
    st = _status_runtime()
    lg = _logger_runtime()
    st.break_line()
    lg.emit(severity=severity, channel="CORE", message=line + "\n", kind=kind)


def stage_do(stage: str) -> None:
    _status_runtime().set_stage(stage)
    _emit_core(severity="INFO", line=f"DO: {stage}", kind="DO")


def stage_ok(stage: str) -> None:
    _emit_core(severity="INFO", line=f"OK: {stage}", kind="OK")


def stage_fail(stage: str) -> None:
    _emit_core(severity="ERROR", line=f"FAIL: {stage}", kind="FAIL")


def gate_progress(token: str) -> None:
    kind, _, stage = token.partition(":")
    if not stage or kind not in ("DO", "OK", "FAIL"):
        return
    _status_runtime().set_stage(stage)
    if kind == "DO":
        _emit_core(severity="INFO", line=f"DO: {stage}", kind="DO")
    elif kind == "OK":
        _emit_core(severity="INFO", line=f"OK: {stage}", kind="OK")
    else:
        _emit_core(severity="ERROR", line=f"FAIL: {stage}", kind="FAIL")


def parse_gate_list(msg: str) -> list[str]:
    if "gates failed:" in msg:
        tail = msg.split("gates failed:", 1)[1]
        parts = [p.strip() for p in tail.split(",")]
        return [p for p in parts if p]
    if "gate failed:" in msg:
        tail = msg.split("gate failed:", 1)[1].strip()
        first = tail.split()[0] if tail else ""
        return [first] if first else []
    return []


def stage_rank(stage: str) -> int:
    order = [
        "PATCH_APPLY",
        "SCOPE",
        "PROMOTE",
        "PREFLIGHT",
        "SECURITY",
        "GATE_COMPILE",
        "GATE_RUFF",
        "GATE_PYTEST",
        "GATE_MYPY",
        "GATE_DOCS",
        "GATE_BADGUYS",
        "GATES",
        "INTERNAL",
    ]
    try:
        return order.index(stage)
    except ValueError:
        return 10_000


_stage_do = stage_do
_stage_ok = stage_ok
_stage_fail = stage_fail
_gate_progress = gate_progress
_parse_gate_list = parse_gate_list
_stage_rank = stage_rank
