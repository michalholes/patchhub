from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy, build_policy
    from am_patch.engine import build_paths_and_logger, finalize_and_report
    from am_patch.errors import CANCEL_EXIT_CODE, RunnerCancelledError, RunnerError
    from am_patch.log import Logger
    from am_patch.repo_root import (
        consume_resolve_repo_root_diagnostic,
        resolve_repo_root,
    )
    from am_patch.run_result import RunResult

    return (
        Logger,
        Policy,
        RunnerCancelledError,
        RunnerError,
        RunResult,
        build_policy,
        finalize_and_report,
        resolve_repo_root,
        build_paths_and_logger,
        consume_resolve_repo_root_diagnostic,
        CANCEL_EXIT_CODE,
    )


def _mk_logger(
    tmp_path: Path,
    *,
    stage: str = "PREFLIGHT",
    json_enabled: bool = False,
    run_timeout_s: int = 7,
):
    logger_cls, *_ = _import_am_patch()
    return logger_cls(
        log_path=tmp_path / "am_patch.log",
        symlink_path=tmp_path / "am_patch.symlink",
        screen_level="quiet",
        log_level="quiet",
        symlink_enabled=False,
        json_enabled=json_enabled,
        json_path=(tmp_path / "am_patch.jsonl") if json_enabled else None,
        stage_provider=lambda: stage,
        run_timeout_s=run_timeout_s,
    )


def test_run_logged_timeout_raises_gate_failure(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, stage="GATE_PYTEST", run_timeout_s=1)
    _, _, _, runner_error_cls, *_ = _import_am_patch()

    try:
        with pytest.raises(runner_error_cls) as excinfo:
            logger.run_logged([sys.executable, "-c", "import time; time.sleep(30)"])
    finally:
        logger.close()

    assert excinfo.value.stage == "GATES"
    assert excinfo.value.category == "TIMEOUT"
    assert "gate failed: pytest" in excinfo.value.message
    assert "timeout after 1s" in excinfo.value.message


def test_run_logged_timeout_soft_fail_returns_run_result(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, run_timeout_s=1)

    try:
        res = logger.run_logged(
            [
                sys.executable,
                "-c",
                "import time; print('x', flush=True); time.sleep(30)",
            ],
            timeout_hard_fail=False,
        )
    finally:
        logger.close()

    assert res.returncode == 124
    assert res.stdout in ("", "x\n")
    assert "subprocess timeout after 1s" in res.stderr


def test_run_logged_emits_json_run_event(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, stage="GATE_PYTEST", json_enabled=True)
    try:
        logger.run_logged([sys.executable, "-c", "print('ok')"])
    finally:
        logger.close()

    json_lines = (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in json_lines]
    assert any(
        evt.get("type") == "log"
        and evt.get("stage") == "GATE_PYTEST"
        and evt.get("kind") == "RUN"
        and evt.get("msg") == "RUN"
        for evt in events
    )


def test_run_logged_streams_live_json_before_process_exit(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, stage="GATE_PYTEST", json_enabled=True)
    done = threading.Event()
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            logger.run_logged(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; "
                        "sys.stdout.write('first\\n'); sys.stdout.flush(); "
                        "time.sleep(0.5); "
                        "sys.stdout.write('tail'); sys.stdout.flush()"
                    ),
                ]
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5.0
        seen_live = False
        while time.monotonic() < deadline:
            json_path = tmp_path / "am_patch.jsonl"
            if json_path.exists():
                events = [
                    json.loads(line)
                    for line in json_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                msgs = [
                    evt.get("msg")
                    for evt in events
                    if evt.get("kind") == "SUBPROCESS_STDOUT"
                ]
                if "first" in msgs:
                    seen_live = True
                    assert not done.is_set()
                    break
            time.sleep(0.05)
        assert seen_live
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        assert not errors
        final_events = [
            json.loads(line)
            for line in (tmp_path / "am_patch.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        msgs = [
            evt.get("msg")
            for evt in final_events
            if evt.get("kind") == "SUBPROCESS_STDOUT"
        ]
        assert msgs == ["first", "tail"]
    finally:
        logger.close()


class _FakeNonTtyStderr:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def isatty(self) -> bool:
        return False

    def write(self, s: str) -> int:
        self.parts.append(s)
        return len(s)

    def flush(self) -> None:
        return None


class _FakeTtyStderr:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def isatty(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self.events.append(("stderr", s))
        return len(s)

    def flush(self) -> None:
        return None


def test_status_heartbeat_reaches_json_only_during_long_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.status import StatusReporter

    fake_stderr = _FakeNonTtyStderr()
    monkeypatch.setattr("am_patch.status.sys.stderr", fake_stderr)

    policy = Policy()
    policy.current_log_symlink_enabled = False
    policy.json_out = True

    status = StatusReporter(enabled=True, interval_tty=0.01, interval_non_tty=0.01)
    ctx = build_startup_logger_and_ipc(
        cli=SimpleNamespace(issue_id="999", mode="workspace"),
        policy=policy,
        patch_dir=tmp_path,
        log_path=tmp_path / "am_patch.log",
        json_path=tmp_path / "am_patch.jsonl",
        status=status,
        verbosity="normal",
        log_level="quiet",
        symlink_path=tmp_path / "am_patch.symlink",
    )

    try:
        status.start()
        status.set_stage("GATE_PYTEST")
        ctx.logger.run_logged(
            [sys.executable, "-c", "import time; time.sleep(0.25); print('ok')"]
        )
    finally:
        status.stop()
        ctx.logger.close()

    json_lines = (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in json_lines]
    assert any(
        evt.get("type") == "log"
        and evt.get("stage") == "GATE_PYTEST"
        and evt.get("kind") == "HEARTBEAT"
        and evt.get("msg") == "HEARTBEAT"
        for evt in events
    )
    assert "HEARTBEAT" not in (tmp_path / "am_patch.log").read_text(encoding="utf-8")


def test_disabled_status_does_not_emit_json_heartbeat(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.status import StatusReporter

    policy = Policy()
    policy.current_log_symlink_enabled = False
    policy.json_out = True

    status = StatusReporter(enabled=False, interval_tty=0.01, interval_non_tty=0.01)
    ctx = build_startup_logger_and_ipc(
        cli=SimpleNamespace(issue_id="1000", mode="workspace"),
        policy=policy,
        patch_dir=tmp_path,
        log_path=tmp_path / "am_patch.log",
        json_path=tmp_path / "am_patch.jsonl",
        status=status,
        verbosity="normal",
        log_level="quiet",
        symlink_path=tmp_path / "am_patch.symlink",
    )

    try:
        status.start()
        time.sleep(0.03)
    finally:
        status.stop()
        ctx.logger.close()

    json_lines = (tmp_path / "am_patch.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in json_lines]
    assert not any(evt.get("kind") == "HEARTBEAT" for evt in events)


def test_resolve_repo_root_timeout_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    *_, resolve_repo_root, _, consume_resolve_repo_root_diagnostic, _ = (
        _import_am_patch()
    )

    import subprocess

    def _boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=3)

    monkeypatch.setattr("am_patch.repo_root.subprocess.run", _boom)
    monkeypatch.chdir(tmp_path)

    assert resolve_repo_root(timeout_s=3) == tmp_path
    diagnostic = consume_resolve_repo_root_diagnostic()
    assert diagnostic is not None
    assert "repo-root fallback to Path.cwd()" in diagnostic
    assert "TimeoutExpired" in diagnostic


def test_build_paths_and_logger_defaults_target_to_runner_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (
        _,
        policy_cls,
        _,
        _,
        _,
        _,
        _,
        _,
        build_paths_and_logger,
        consume_resolve_repo_root_diagnostic,
        _,
    ) = _import_am_patch()

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
    }

    ctx = None
    try:
        policy = policy_cls()
        policy.repo_root = None
        policy.target_repo_roots = ["/home/pi/audiomason2", "/home/pi/patchhub"]
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "warning"
        policy.json_out = False
        policy.ipc_socket_enabled = False

        cli = SimpleNamespace(issue_id="1000", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        expected_runner_root = Path(__file__).resolve().parent.parent
        assert ctx.runner_root == expected_runner_root
        assert ctx.repo_root == Path("/home/pi/audiomason2")
        assert ctx.effective_target_repo_name == "audiomason2"
        assert ctx.artifacts_root == expected_runner_root
        log_data = ctx.log_path.read_text(encoding="utf-8")
        assert "repo-root fallback to Path.cwd()" not in log_data
        assert consume_resolve_repo_root_diagnostic() is None
    finally:
        if ctx is not None:
            ctx.status.stop()
            ctx.logger.close()
        for key in (
            "status",
            "logger",
            "policy",
            "repo_root",
            "paths",
            "cli",
            "run_badguys",
            "RunnerError",
        ):
            setattr(runtime_mod, key, old[key])


def test_build_paths_and_logger_breaks_active_tty_status_before_failure_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (
        _,
        policy_cls,
        _,
        _,
        _,
        _,
        _,
        _,
        build_paths_and_logger,
        _,
        _,
    ) = _import_am_patch()

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
    }

    events: list[tuple[str, str]] = []
    fake_stderr = _FakeTtyStderr(events)
    monkeypatch.setattr("am_patch.status.sys.stderr", fake_stderr)

    ctx = None
    try:
        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2"]
        policy.patch_dir = str(tmp_path / "patches")
        policy.current_log_symlink_enabled = False
        policy.verbosity = "normal"
        policy.log_level = "quiet"
        policy.json_out = False
        policy.ipc_socket_enabled = False

        cli = SimpleNamespace(issue_id="1000", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        ctx.status.set_stage("GATE_PYTEST")
        time.sleep(0.05)

        def _write_screen(s: str) -> None:
            events.append(("screen", s))

        ctx.logger._write_screen = _write_screen
        ctx.logger.run_logged(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom\n'); sys.stderr.flush(); raise SystemExit(1)",
            ]
        )

        first_screen_index = next(
            i for i, event in enumerate(events) if event[0] == "screen"
        )
        assert any(
            kind == "stderr" and payload == "\n"
            for kind, payload in events[:first_screen_index]
        )
        screen_payloads = [payload for kind, payload in events if kind == "screen"]
        assert screen_payloads[0].startswith("\n" + ("=" * 80))
        assert any(payload == "[stderr]\n" for payload in screen_payloads)
        assert any("boom\n" in payload for payload in screen_payloads)
    finally:
        if ctx is not None:
            ctx.status.stop()
            ctx.logger.close()
        for key in (
            "status",
            "logger",
            "policy",
            "repo_root",
            "paths",
            "cli",
            "run_badguys",
            "RunnerError",
        ):
            setattr(runtime_mod, key, old[key])


def test_build_policy_validates_runner_subprocess_timeout() -> None:
    _, policy_cls, _, runner_error_cls, _, build_policy, *_ = _import_am_patch()
    defaults = policy_cls()

    policy = build_policy(defaults, {"runner_subprocess_timeout_s": 0})
    assert policy.runner_subprocess_timeout_s == 0

    policy = build_policy(defaults, {"runner_subprocess_timeout_s": 45})
    assert policy.runner_subprocess_timeout_s == 45

    with pytest.raises(runner_error_cls) as excinfo:
        build_policy(defaults, {"runner_subprocess_timeout_s": -1})

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"
    assert excinfo.value.message == "runner_subprocess_timeout_s must be >= 0"


def test_ipc_cancel_interrupts_active_subprocess(tmp_path: Path) -> None:
    imports = _import_am_patch()
    runner_cancelled_cls = imports[2]

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.status import StatusReporter

    policy = Policy()
    policy.current_log_symlink_enabled = False
    policy.ipc_socket_enabled = True
    status = StatusReporter(enabled=False)
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


class _FakeStatus:
    def stop(self) -> None:
        return None


def test_finalize_and_report_emits_canceled_result(tmp_path: Path) -> None:
    imports = _import_am_patch()
    logger_cls = imports[0]
    run_result_cls = imports[4]
    finalize_and_report = imports[6]
    cancel_exit_code = imports[10]
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
    text = (tmp_path / "am_patch.log").read_text(encoding="utf-8")
    assert "RESULT: CANCELED" in text


def test_status_heartbeat_and_result_event_keep_ndjson_valid(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.final_summary import build_terminal_summary
    from am_patch.status import StatusReporter

    policy = Policy()
    policy.current_log_symlink_enabled = False
    policy.json_out = True

    status = StatusReporter(enabled=True, interval_tty=0.01, interval_non_tty=0.01)
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
        ctx.logger.run_logged(
            [sys.executable, "-c", "import time; time.sleep(0.25); print('ok')"]
        )
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
        for line in (tmp_path / "am_patch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
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


def test_build_paths_and_logger_supports_cross_repo_target_and_artifacts_root(
    tmp_path: Path,
) -> None:
    (_, policy_cls, _, _, _, _, _, _, build_paths_and_logger, _, _) = _import_am_patch()

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
    }

    ctx = None
    try:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()

        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2", "/home/pi/patchhub"]
        policy.active_target_repo_root = "/home/pi/patchhub"
        policy.artifacts_root = str(artifacts)
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "quiet"

        cli = SimpleNamespace(issue_id="1001", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        assert ctx.repo_root == Path("/home/pi/patchhub")
        assert ctx.effective_target_repo_name == "patchhub"
        assert ctx.artifacts_root == artifacts.resolve()
        assert ctx.patch_root == artifacts.resolve() / policy.patch_dir_name
        assert ctx.paths.patch_dir == ctx.patch_root
        assert ctx.paths.workspaces_dir.parent == ctx.patch_root
    finally:
        if ctx is not None:
            if ctx.ipc is not None:
                ctx.ipc.stop()
            ctx.status.stop()
            ctx.logger.close()
        for key, value in old.items():
            setattr(runtime_mod, key, value)
