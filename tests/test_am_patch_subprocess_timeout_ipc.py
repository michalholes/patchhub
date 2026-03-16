from __future__ import annotations

import json
import threading
import time
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_am_patch():
    from am_patch.config import Policy
    from am_patch.engine import finalize_and_report
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.errors import CANCEL_EXIT_CODE, RunnerCancelledError
    from am_patch.final_summary import build_terminal_summary
    from am_patch.log import Logger
    from am_patch.run_result import RunResult
    from am_patch.status import StatusReporter

    return (
        Policy,
        Logger,
        RunResult,
        build_startup_logger_and_ipc,
        finalize_and_report,
        build_terminal_summary,
        StatusReporter,
        RunnerCancelledError,
        CANCEL_EXIT_CODE,
    )


class _FakeStatus:
    def stop(self) -> None:
        return None


def test_ipc_cancel_interrupts_active_subprocess(tmp_path: Path) -> None:
    (
        policy_cls,
        _,
        _,
        build_startup_logger_and_ipc,
        _,
        _,
        status_cls,
        runner_cancelled_cls,
        _,
    ) = _import_am_patch()
    policy = policy_cls()
    policy.current_log_symlink_enabled = False
    policy.ipc_socket_enabled = True
    status = status_cls(enabled=False)
    ctx = build_startup_logger_and_ipc(
        cli=SimpleNamespace(issue_id="1001", mode="workspace"),
        policy=policy,
        patch_dir=tmp_path,
        log_path=tmp_path / "am_patch.log",
        json_path=None,
        status=status,
        verbosity="quiet",
        log_level="quiet",
        symlink_path=tmp_path / "am_patch.symlink",
    )
    assert ctx.ipc is not None
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            ctx.logger.run_logged([sys.executable, "-c", "import time; time.sleep(30)"])
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    time.sleep(0.3)
    ctx.ipc.request_cancel()
    worker.join(timeout=5.0)
    try:
        assert not worker.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], runner_cancelled_cls)
    finally:
        ctx.ipc.stop()
        ctx.logger.close()


def test_finalize_and_report_emits_canceled_result(tmp_path: Path) -> None:
    (
        _,
        logger_cls,
        run_result_cls,
        _,
        finalize_and_report,
        _,
        _,
        _,
        cancel_exit_code,
    ) = _import_am_patch()
    logger = logger_cls(
        log_path=tmp_path / "am_patch.log",
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="quiet",
        symlink_enabled=False,
    )
    ctx = SimpleNamespace(
        policy=SimpleNamespace(test_mode=False),
        log_path=tmp_path / "am_patch.log",
        logger=logger,
        status=_FakeStatus(),
        verbosity="quiet",
        log_level="quiet",
        json_path=None,
        isolated_work_patch_dir=None,
    )
    result = run_result_cls(exit_code=cancel_exit_code)
    import am_patch.engine as engine_mod

    original = engine_mod.run_post_run_pipeline

    def _fake_run_post_run_pipeline(*, ctx: object, result: object) -> int:
        del ctx, result
        return cancel_exit_code

    engine_mod.run_post_run_pipeline = _fake_run_post_run_pipeline
    try:
        rc = finalize_and_report(ctx, result)
    finally:
        engine_mod.run_post_run_pipeline = original
    assert rc == cancel_exit_code
    assert "RESULT: CANCELED" in (tmp_path / "am_patch.log").read_text()


def test_status_heartbeat_and_result_event_keep_ndjson_valid(tmp_path: Path) -> None:
    (
        policy_cls,
        _,
        _,
        build_startup_logger_and_ipc,
        _,
        build_terminal_summary,
        status_cls,
        _,
        _,
    ) = _import_am_patch()
    policy = policy_cls()
    policy.current_log_symlink_enabled = False
    policy.json_out = True
    status = status_cls(enabled=True, interval_tty=0.01, interval_non_tty=0.01)
    ctx = build_startup_logger_and_ipc(
        cli=SimpleNamespace(mode="workspace", issue_id="1001"),
        policy=policy,
        patch_dir=tmp_path,
        log_path=tmp_path / "am_patch.log",
        json_path=tmp_path / "am_patch.jsonl",
        status=status,
        verbosity="quiet",
        log_level="quiet",
        symlink_path=tmp_path / "am_patch.symlink",
    )
    try:
        status.start()
        status.set_stage("GATE_PYTEST")
        ctx.logger.run_logged([sys.executable, "-c", "import time; time.sleep(0.25); print('ok')"])
        ctx.logger.emit_json_result(
            summary=build_terminal_summary(
                exit_code=0,
                commit_and_push=False,
                final_commit_sha=None,
                final_pushed_files=None,
                push_ok_for_posthook=None,
                final_fail_stage=None,
                final_fail_reason=None,
                log_path=tmp_path / "am_patch.log",
                json_path=tmp_path / "am_patch.jsonl",
            )
        )
    finally:
        status.stop()
        ctx.logger.close()
    events = [
        json.loads(line)
        for line in (tmp_path / "am_patch.jsonl").read_text().splitlines()
        if line.strip()
    ]
    result_evt = next(evt for evt in events if evt.get("type") == "result")
    assert any(
        evt.get("type") == "log"
        and evt.get("stage") == "GATE_PYTEST"
        and evt.get("kind") == "HEARTBEAT"
        and evt.get("msg") == "HEARTBEAT"
        for evt in events
    )
    assert result_evt["terminal_status"] == "success"
    assert result_evt["final_stage"] is None
    assert result_evt["final_reason"] is None
    assert result_evt["json_path"] == str(tmp_path / "am_patch.jsonl")
