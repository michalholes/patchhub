from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.engine import finalize_and_report
    from am_patch.errors import RunnerError
    from am_patch.log import Logger
    from am_patch.run_result import RunResult, _normalize_failure_summary
    from am_patch.runtime import _parse_gate_list, _stage_rank

    return (
        Logger,
        RunResult,
        RunnerError,
        _normalize_failure_summary,
        _parse_gate_list,
        _stage_rank,
        finalize_and_report,
    )


def _mk_context(
    tmp_path: Path,
    *,
    commit_and_push: bool,
):
    logger_cls, *_ = _import_am_patch()
    log_path = tmp_path / "am_patch.log"
    json_path = tmp_path / "am_patch.jsonl"
    logger = logger_cls(
        log_path=log_path,
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="quiet",
        symlink_enabled=False,
        json_enabled=True,
        json_path=json_path,
    )
    ctx = SimpleNamespace(
        policy=SimpleNamespace(test_mode=False, commit_and_push=commit_and_push),
        log_path=log_path,
        logger=logger,
        status=SimpleNamespace(stop=lambda: None),
        verbosity="quiet",
        log_level="quiet",
        json_path=json_path,
        isolated_work_patch_dir=None,
        effective_target_repo_name="patchhub",
    )
    return ctx, logger, json_path


def _read_result_event(json_path: Path) -> dict[str, object]:
    events = [
        json.loads(line)
        for line in json_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return next(evt for evt in events if evt.get("type") == "result")


def test_normalize_failure_summary_maps_gate_failures() -> None:
    (
        _,
        _,
        runner_error_cls,
        _normalize_failure_summary,
        parse_gate_list,
        stage_rank,
        _,
    ) = _import_am_patch()

    stage, reason = _normalize_failure_summary(
        error=runner_error_cls("GATES", "GATES", "gates failed: ruff, pytest"),
        primary_fail_stage=None,
        secondary_failures=[],
        parse_gate_list=parse_gate_list,
        stage_rank=stage_rank,
    )

    assert stage == "GATE_RUFF, GATE_PYTEST"
    assert reason == "gates failed"


def test_normalize_failure_summary_maps_audit_failures() -> None:
    (
        _,
        _,
        runner_error_cls,
        _normalize_failure_summary,
        parse_gate_list,
        stage_rank,
        _,
    ) = _import_am_patch()

    stage, reason = _normalize_failure_summary(
        error=runner_error_cls("AUDIT", "AUDIT_REPORT_FAILED", "audit/audit_report.py failed"),
        primary_fail_stage=None,
        secondary_failures=[],
        parse_gate_list=parse_gate_list,
        stage_rank=stage_rank,
    )

    assert stage == "AUDIT"
    assert reason == "audit failed"


def test_normalize_failure_summary_keeps_preflight_reason_generic() -> None:
    (
        _,
        _,
        runner_error_cls,
        _normalize_failure_summary,
        parse_gate_list,
        stage_rank,
        _,
    ) = _import_am_patch()

    stage, reason = _normalize_failure_summary(
        error=runner_error_cls(
            "PREFLIGHT",
            "PATCH_ASCII",
            "patch contains non-ascii characters: patch.zip",
        ),
        primary_fail_stage=None,
        secondary_failures=[],
        parse_gate_list=parse_gate_list,
        stage_rank=stage_rank,
    )

    assert stage == "PREFLIGHT"
    assert reason == "invalid inputs"


def test_finalize_and_report_emits_failure_result_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, run_result_cls, _, _, _, _, finalize_and_report = _import_am_patch()
    ctx, logger, json_path = _mk_context(tmp_path, commit_and_push=False)
    result = run_result_cls(
        exit_code=1,
        final_fail_stage="GATE_PYTEST",
        final_fail_reason="gates failed",
    )

    import am_patch.engine as engine_mod

    monkeypatch.setattr(engine_mod, "run_post_run_pipeline", lambda ctx, result: 1)
    try:
        rc = finalize_and_report(ctx, result)
    finally:
        logger.close()

    result_evt = _read_result_event(json_path)

    assert rc == 1
    assert result_evt["terminal_status"] == "fail"
    assert result_evt["final_stage"] == "GATE_PYTEST"
    assert result_evt["final_reason"] == "gates failed"
    assert result_evt["final_commit_sha"] is None
    assert result_evt["push_status"] is None
    assert result_evt["effective_target_repo_name"] == "patchhub"
    assert result_evt["json_path"] == str(json_path)


def test_finalize_and_report_emits_success_result_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, run_result_cls, _, _, _, _, finalize_and_report = _import_am_patch()
    ctx, logger, json_path = _mk_context(tmp_path, commit_and_push=True)
    result = run_result_cls(
        exit_code=0,
        final_commit_sha="deadbeef",
        final_pushed_files=["alpha.py"],
        push_ok_for_posthook=True,
    )

    import am_patch.engine as engine_mod

    monkeypatch.setattr(engine_mod, "run_post_run_pipeline", lambda ctx, result: 0)
    try:
        rc = finalize_and_report(ctx, result)
    finally:
        logger.close()

    result_evt = _read_result_event(json_path)

    assert rc == 0
    assert result_evt["terminal_status"] == "success"
    assert result_evt["final_stage"] is None
    assert result_evt["final_reason"] is None
    assert result_evt["final_commit_sha"] == "deadbeef"
    assert result_evt["push_status"] == "OK"
    assert result_evt["effective_target_repo_name"] == "patchhub"
    assert result_evt["json_path"] == str(json_path)
