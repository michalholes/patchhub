from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_runner_script_module():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    os.environ["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"
    script_path = scripts_dir / "am_patch.py"
    module_name = "am_patch_main_final_summary_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeLogger:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakeStatus:
    def stop(self) -> None:
        return None


def test_main_converts_unhandled_run_exception_into_finalized_fail_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_runner_script_module()
    logger = _FakeLogger()
    cli = SimpleNamespace(mode="workspace")
    policy = SimpleNamespace(
        ipc_socket_cleanup_delay_success_s=0,
        ipc_socket_cleanup_delay_failure_s=0,
        test_mode=False,
    )
    ctx = SimpleNamespace(cli=cli, policy=policy, logger=logger, ipc=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        mod, "build_effective_policy", lambda argv: (cli, policy, Path("cfg"), "cfg")
    )
    monkeypatch.setattr(mod, "build_paths_and_logger", lambda *args: ctx)

    def _run_mode(_ctx):
        raise ValueError("boom")

    def _finalize_and_report(_ctx, result):
        captured["result"] = result
        return 9

    monkeypatch.setattr(mod, "run_mode", _run_mode)
    monkeypatch.setattr(mod, "finalize_and_report", _finalize_and_report)

    rc = mod.main([])

    assert rc == 9
    result = captured["result"]
    assert result.exit_code == 1
    assert result.final_fail_stage == "INTERNAL"
    assert result.final_fail_reason == "unexpected error"
    assert "ERROR DETAIL: INTERNAL:INTERNAL: ValueError: boom" in result.final_fail_detail
    assert "AM_PATCH_FAILURE_FINGERPRINT:" in result.final_fail_fingerprint
    assert "ValueError: boom" in result.final_fail_fingerprint
    assert logger.close_calls == 1


def test_finalize_and_report_reuses_one_terminal_summary_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    import am_patch.engine as engine_mod
    from am_patch.engine import finalize_and_report
    from am_patch.log import Logger
    from am_patch.run_result import RunResult

    log_path = tmp_path / "am_patch.log"
    logger = Logger(
        log_path=log_path,
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="normal",
        symlink_enabled=False,
    )
    ctx = SimpleNamespace(
        policy=SimpleNamespace(test_mode=False, commit_and_push=True),
        log_path=log_path,
        logger=logger,
        status=_FakeStatus(),
        verbosity="quiet",
        log_level="normal",
        json_path=tmp_path / "am_patch.jsonl",
        isolated_work_patch_dir=None,
    )
    result = RunResult(
        exit_code=0,
        final_commit_sha="deadbeef",
        final_pushed_files=["alpha.py"],
        push_ok_for_posthook=True,
    )
    captured: dict[str, object] = {}

    def _capture_json_result(*, summary) -> None:
        captured["json_summary"] = summary

    def _capture_final_summary(**kwargs) -> None:
        captured["final_summary"] = kwargs["summary"]

    monkeypatch.setattr(logger, "emit_json_result", _capture_json_result)
    monkeypatch.setattr(engine_mod, "emit_final_summary", _capture_final_summary)
    monkeypatch.setattr(engine_mod, "run_post_run_pipeline", lambda ctx, result: 0)
    try:
        rc = finalize_and_report(ctx, result)
    finally:
        logger.close()

    assert rc == 0
    assert captured["json_summary"] is captured["final_summary"]
    assert captured["json_summary"].terminal_status == "success"
    assert captured["json_summary"].final_commit_sha == "deadbeef"
    assert captured["json_summary"].push_status == "OK"


def test_finalize_and_report_keeps_fail_summary_when_json_result_emit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    import am_patch.engine as engine_mod
    from am_patch.engine import finalize_and_report
    from am_patch.log import Logger
    from am_patch.run_result import RunResult

    log_path = tmp_path / "am_patch.log"
    logger = Logger(
        log_path=log_path,
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="normal",
        symlink_enabled=False,
    )
    ctx = SimpleNamespace(
        policy=SimpleNamespace(test_mode=False, commit_and_push=False),
        log_path=log_path,
        logger=logger,
        status=_FakeStatus(),
        verbosity="quiet",
        log_level="normal",
        json_path=None,
        isolated_work_patch_dir=None,
    )
    result = RunResult(
        exit_code=1,
        final_fail_stage=("GATE_COMPILE, GATE_RUFF, GATE_MYPY, GATE_DOCS, GATE_MONOLITH"),
        final_fail_reason="gates failed",
        final_fail_detail=(
            "ERROR DETAIL: GATES:GATES: gates failed: compile, ruff, mypy, monolith, docs\n"
        ),
    )

    def _raise_json_result(**_kwargs) -> None:
        raise RuntimeError("json result failed")

    monkeypatch.setattr(logger, "emit_json_result", _raise_json_result)
    monkeypatch.setattr(engine_mod, "run_post_run_pipeline", lambda ctx, result: 1)
    try:
        rc = finalize_and_report(ctx, result)
    finally:
        logger.close()

    assert rc == 1
    data = log_path.read_text(encoding="utf-8")
    assert "RESULT: FAIL" in data
    assert "STAGE: GATE_COMPILE, GATE_RUFF, GATE_MYPY, GATE_DOCS, GATE_MONOLITH" in data
    assert "REASON: gates failed" in data
    assert f"LOG: {log_path}" in data
