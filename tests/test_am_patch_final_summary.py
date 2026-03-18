from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.final_summary import (
        build_terminal_summary,
        emit_final_summary,
        render_summary_lines,
    )
    from am_patch.log import Logger

    return Logger, build_terminal_summary, emit_final_summary, render_summary_lines


def _mk_logger(
    tmp_path: Path,
    *,
    screen_level: str,
    log_level: str,
    json_enabled: bool = False,
):
    logger_cls, *_ = _import_am_patch()
    log_path = tmp_path / "am_patch.log"
    symlink_path = tmp_path / "am_patch.symlink"
    return logger_cls(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level=screen_level,
        log_level=log_level,
        symlink_enabled=False,
        json_enabled=json_enabled,
        json_path=(tmp_path / "am_patch.jsonl") if json_enabled else None,
    )


def _expected_render(
    summary,
    *,
    screen_quiet: bool,
    log_quiet: bool,
) -> tuple[str, str, list[tuple[str, str]]]:
    *_, render_summary_lines = _import_am_patch()
    screen_parts: list[str] = []
    log_parts: list[str] = []
    machine_parts: list[tuple[str, str]] = []
    for message, kind, always_screen, always_log in render_summary_lines(summary):
        if always_screen or not screen_quiet:
            screen_parts.append(message)
        if always_log or not log_quiet:
            log_parts.append(message)
        machine_message = message[:-1] if message.endswith("\n") else message
        machine_parts.append((kind, machine_message))
    return "".join(screen_parts), "".join(log_parts), machine_parts


def test_success_summary_log_events_and_human_output_share_one_render(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    _, build_terminal_summary, emit_final_summary, _ = _import_am_patch()
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="normal", json_enabled=True)
    log_path = tmp_path / "am_patch.log"
    summary = build_terminal_summary(
        exit_code=0,
        commit_and_push=True,
        final_commit_sha="abc1234",
        final_pushed_files=["alpha.py", "beta.py"],
        push_ok_for_posthook=True,
        final_fail_stage=None,
        final_fail_reason=None,
        log_path=log_path,
        json_path=tmp_path / "am_patch.jsonl",
    )
    try:
        emit_final_summary(
            logger=logger,
            summary=summary,
            final_fail_detail=None,
            final_fail_fingerprint=None,
            screen_quiet=False,
            log_quiet=False,
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = log_path.read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary_events = [
        (evt["kind"], evt["msg"])
        for evt in events
        if evt.get("type") == "log" and evt.get("summary") is True
    ]
    expected_screen, expected_log, expected_machine = _expected_render(
        summary,
        screen_quiet=False,
        log_quiet=False,
    )

    assert out == expected_screen
    assert data == expected_log
    assert summary_events == expected_machine


def test_fail_summary_keeps_quiet_sinks_and_machine_render_consistent(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    _, build_terminal_summary, emit_final_summary, _ = _import_am_patch()
    logger = _mk_logger(tmp_path, screen_level="quiet", log_level="quiet", json_enabled=True)
    log_path = tmp_path / "am_patch.log"
    summary = build_terminal_summary(
        exit_code=1,
        commit_and_push=False,
        final_commit_sha=None,
        final_pushed_files=None,
        push_ok_for_posthook=None,
        final_fail_stage="PREFLIGHT",
        final_fail_reason="invalid inputs",
        log_path=log_path,
        json_path=tmp_path / "am_patch.jsonl",
    )
    detail = "ERROR DETAIL: PREFLIGHT:PATCH_ASCII: bad patch\n"
    fingerprint = "AM_PATCH_FAILURE_FINGERPRINT:\n- stage: PREFLIGHT\n- category: PATCH_ASCII\n"
    try:
        emit_final_summary(
            logger=logger,
            summary=summary,
            final_fail_detail=detail,
            final_fail_fingerprint=fingerprint,
            screen_quiet=True,
            log_quiet=True,
        )
    finally:
        logger.close()

    out = capsys.readouterr().out
    data = log_path.read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary_events = [
        (evt["kind"], evt["msg"])
        for evt in events
        if evt.get("type") == "log" and evt.get("summary") is True
    ]
    expected_screen, expected_log, expected_machine = _expected_render(
        summary,
        screen_quiet=True,
        log_quiet=True,
    )

    assert out == detail + expected_screen
    assert data == detail + fingerprint + expected_log
    assert summary_events == expected_machine
    assert "AM_PATCH_FAILURE_FINGERPRINT" not in out


def test_fail_summary_keeps_log_summary_when_screen_sink_fails(tmp_path: Path) -> None:
    _, build_terminal_summary, emit_final_summary, _ = _import_am_patch()
    logger = _mk_logger(tmp_path, screen_level="normal", log_level="normal")
    log_path = tmp_path / "am_patch.log"
    summary = build_terminal_summary(
        exit_code=1,
        commit_and_push=False,
        final_commit_sha=None,
        final_pushed_files=None,
        push_ok_for_posthook=None,
        final_fail_stage=("GATE_COMPILE, GATE_RUFF, GATE_MYPY, GATE_DOCS, GATE_MONOLITH"),
        final_fail_reason="gates failed",
        log_path=log_path,
        json_path=None,
    )

    def _write_screen(_message: str) -> None:
        raise OSError("screen sink failed")

    logger._write_screen = _write_screen  # type: ignore[method-assign]
    try:
        emit_final_summary(
            logger=logger,
            summary=summary,
            final_fail_detail=(
                "ERROR DETAIL: GATES:GATES: gates failed: compile, ruff, mypy, monolith, docs\n"
            ),
            final_fail_fingerprint=(
                "AM_PATCH_FAILURE_FINGERPRINT:\n- stage: GATES\n- category: GATES\n"
            ),
            screen_quiet=False,
            log_quiet=False,
        )
    finally:
        logger.close()

    data = log_path.read_text(encoding="utf-8")

    assert "RESULT: FAIL" in data
    assert "STAGE: GATE_COMPILE, GATE_RUFF, GATE_MYPY, GATE_DOCS, GATE_MONOLITH" in data
    assert "REASON: gates failed" in data
    assert f"LOG: {log_path}" in data
    assert "AM_PATCH_FAILURE_FINGERPRINT" in data
