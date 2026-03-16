from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import CANCEL_EXIT_CODE

if TYPE_CHECKING:
    from .log import Logger


@dataclass(frozen=True)
class TerminalSummary:
    ok: bool
    return_code: int
    terminal_status: str
    final_stage: str | None
    final_reason: str | None
    final_commit_sha: str | None
    push_status: str | None
    log_path: Path
    json_path: Path | None
    final_pushed_files: list[str] | None
    commit_and_push: bool


def build_terminal_summary(
    *,
    exit_code: int,
    commit_and_push: bool,
    final_commit_sha: str | None,
    final_pushed_files: list[str] | None,
    push_ok_for_posthook: bool | None,
    final_fail_stage: str | None,
    final_fail_reason: str | None,
    log_path: Path,
    json_path: Path | None,
) -> TerminalSummary:
    terminal_status = _terminal_status(exit_code)
    return TerminalSummary(
        ok=exit_code == 0,
        return_code=int(exit_code),
        terminal_status=terminal_status,
        final_stage=_final_stage(terminal_status, final_fail_stage),
        final_reason=_final_reason(terminal_status, final_fail_reason),
        final_commit_sha=(final_commit_sha if terminal_status == "success" else None),
        push_status=_push_status(commit_and_push, push_ok_for_posthook),
        log_path=log_path,
        json_path=json_path,
        final_pushed_files=_final_pushed_files(
            terminal_status,
            final_pushed_files,
        ),
        commit_and_push=bool(commit_and_push),
    )


def result_event_payload(summary: TerminalSummary) -> dict[str, object]:
    return {
        "ok": bool(summary.ok),
        "return_code": int(summary.return_code),
        "terminal_status": summary.terminal_status,
        "final_stage": summary.final_stage,
        "final_reason": summary.final_reason,
        "final_commit_sha": summary.final_commit_sha,
        "push_status": summary.push_status,
        "log_path": str(summary.log_path),
        "json_path": str(summary.json_path) if summary.json_path is not None else None,
    }


def render_summary_lines(summary: TerminalSummary) -> list[tuple[str, str, bool, bool]]:
    if summary.terminal_status == "success":
        return _render_success_lines(summary)
    if summary.terminal_status == "canceled":
        return _render_canceled_lines(summary)
    return _render_fail_lines(summary)


def _final_pushed_files(
    terminal_status: str,
    final_pushed_files: list[str] | None,
) -> list[str] | None:
    if terminal_status != "success" or not isinstance(final_pushed_files, list):
        return None
    return list(final_pushed_files)


def _terminal_status(exit_code: int) -> str:
    if exit_code == 0:
        return "success"
    if exit_code == CANCEL_EXIT_CODE:
        return "canceled"
    return "fail"


def _final_stage(terminal_status: str, final_fail_stage: str | None) -> str | None:
    if terminal_status == "success":
        return None
    return final_fail_stage or "INTERNAL"


def _final_reason(terminal_status: str, final_fail_reason: str | None) -> str | None:
    if terminal_status == "success":
        return None
    if terminal_status == "canceled":
        return "cancel requested"
    return final_fail_reason or "unexpected error"


def _push_status(commit_and_push: bool, push_ok_for_posthook: bool | None) -> str | None:
    if not commit_and_push:
        return None
    if push_ok_for_posthook is True:
        return "OK"
    if push_ok_for_posthook is False:
        return "FAIL"
    return None


def _render_success_lines(summary: TerminalSummary) -> list[tuple[str, str, bool, bool]]:
    lines: list[tuple[str, str, bool, bool]] = [("RESULT: SUCCESS\n", "RESULT", True, True)]
    if summary.push_status == "OK" and summary.final_pushed_files is not None:
        lines.append(("FILES:\n\n", "FILES", False, False))
        lines.extend((f"{line}\n", "TEXT", False, False) for line in summary.final_pushed_files)
    lines.append((f"COMMIT: {summary.final_commit_sha or '(none)'}\n", "COMMIT", False, False))
    if summary.commit_and_push:
        push_text = summary.push_status or "UNKNOWN"
        lines.append((f"PUSH: {push_text}\n", "PUSH", False, False))
    lines.append((f"LOG: {summary.log_path}\n", "TEXT", False, True))
    return lines


def _render_canceled_lines(summary: TerminalSummary) -> list[tuple[str, str, bool, bool]]:
    return [
        ("RESULT: CANCELED\n", "RESULT", True, True),
        (f"STAGE: {summary.final_stage or 'INTERNAL'}\n", "STAGE", False, True),
        (
            f"REASON: {summary.final_reason or 'cancel requested'}\n",
            "REASON",
            False,
            True,
        ),
        (f"LOG: {summary.log_path}\n", "TEXT", False, True),
    ]


def _render_fail_lines(summary: TerminalSummary) -> list[tuple[str, str, bool, bool]]:
    return [
        ("RESULT: FAIL\n", "RESULT", True, True),
        (f"STAGE: {summary.final_stage or 'INTERNAL'}\n", "STAGE", False, False),
        (
            f"REASON: {summary.final_reason or 'unexpected error'}\n",
            "REASON",
            False,
            False,
        ),
        (f"LOG: {summary.log_path}\n", "TEXT", False, False),
    ]


def _emit_logger_message(
    logger: Logger,
    *,
    severity: str,
    channel: str,
    message: str,
    kind: str,
    summary: bool,
    error_detail: bool,
    to_screen: bool,
    to_log: bool,
) -> None:
    with suppress(Exception):
        logger.emit(
            severity=severity,
            channel=channel,
            message=message,
            kind=kind,
            summary=summary,
            error_detail=error_detail,
            to_screen=False,
            to_log=False,
        )
    if to_log:
        with suppress(Exception):
            logger._write_file(message)
    if to_screen:
        with suppress(Exception):
            logger._write_screen(message)


def _emit_summary_line(
    logger: Logger,
    *,
    message: str,
    kind: str,
    to_screen: bool,
    to_log: bool,
) -> None:
    _emit_logger_message(
        logger,
        severity="INFO",
        channel="CORE",
        message=message,
        kind=kind,
        summary=True,
        error_detail=False,
        to_screen=to_screen,
        to_log=to_log,
    )


def emit_final_summary(
    *,
    logger: Logger,
    summary: TerminalSummary,
    final_fail_detail: str | None,
    final_fail_fingerprint: str | None,
    screen_quiet: bool,
    log_quiet: bool,
) -> None:
    if final_fail_detail:
        _emit_logger_message(
            logger,
            severity="ERROR",
            channel="CORE",
            message=final_fail_detail,
            kind="TEXT",
            summary=False,
            error_detail=True,
            to_screen=True,
            to_log=True,
        )
    if final_fail_fingerprint:
        _emit_logger_message(
            logger,
            severity="ERROR",
            channel="CORE",
            message=final_fail_fingerprint,
            kind="TEXT",
            summary=False,
            error_detail=True,
            to_screen=False,
            to_log=True,
        )
    for message, kind, always_screen, always_log in render_summary_lines(summary):
        _emit_summary_line(
            logger,
            message=message,
            kind=kind,
            to_screen=always_screen or not screen_quiet,
            to_log=always_log or not log_quiet,
        )
