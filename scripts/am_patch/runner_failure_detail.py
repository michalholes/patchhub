from __future__ import annotations

from am_patch.errors import RunnerError, fingerprint


def _single_line(message: str) -> str:
    return str(message).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " | ").strip()


def render_runner_error_detail(error: RunnerError) -> str:
    detail = _single_line(error.message)
    return f"ERROR DETAIL: {error.stage}:{error.category}: {detail}\n"


def render_runner_error_fingerprint(error: RunnerError) -> str:
    return fingerprint(error) + "\n"
