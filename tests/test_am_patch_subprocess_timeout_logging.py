from __future__ import annotations

import json
import threading
import time
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    from am_patch.config import Policy
    from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
    from am_patch.engine import build_paths_and_logger
    from am_patch.errors import RunnerError
    from am_patch.log import Logger
    from am_patch.repo_root import consume_resolve_repo_root_diagnostic, resolve_repo_root
    from am_patch.status import StatusReporter

    return (
        Logger,
        Policy,
        RunnerError,
        resolve_repo_root,
        build_paths_and_logger,
        consume_resolve_repo_root_diagnostic,
        build_startup_logger_and_ipc,
        StatusReporter,
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


def test_run_logged_timeout_raises_gate_failure(tmp_path: Path) -> None:
    logger = _mk_logger(tmp_path, stage="GATE_PYTEST", run_timeout_s=1)
    _, _, runner_error_cls, *_ = _import_am_patch()
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
            [sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"],
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
    events = [json.loads(line) for line in (tmp_path / "am_patch.jsonl").read_text().splitlines()]
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
                    json.loads(line) for line in json_path.read_text().splitlines() if line.strip()
                ]
                msgs = [evt.get("msg") for evt in events if evt.get("kind") == "SUBPROCESS_STDOUT"]
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
            for line in (tmp_path / "am_patch.jsonl").read_text().splitlines()
            if line.strip()
        ]
        msgs = [evt.get("msg") for evt in final_events if evt.get("kind") == "SUBPROCESS_STDOUT"]
        assert msgs == ["first", "tail"]
    finally:
        logger.close()


def test_status_heartbeat_reaches_json_only_during_long_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (
        _,
        policy_cls,
        _,
        _,
        _,
        _,
        build_startup_logger_and_ipc,
        status_cls,
    ) = _import_am_patch()
    fake_stderr = _FakeNonTtyStderr()
    monkeypatch.setattr("am_patch.status.sys.stderr", fake_stderr)
    policy = policy_cls()
    policy.current_log_symlink_enabled = False
    policy.json_out = True
    status = status_cls(enabled=True, interval_tty=0.01, interval_non_tty=0.01)
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
        ctx.logger.run_logged([sys.executable, "-c", "import time; time.sleep(0.25); print('ok')"])
    finally:
        status.stop()
        ctx.logger.close()
    events = [json.loads(line) for line in (tmp_path / "am_patch.jsonl").read_text().splitlines()]
    assert any(
        evt.get("type") == "log"
        and evt.get("stage") == "GATE_PYTEST"
        and evt.get("kind") == "HEARTBEAT"
        and evt.get("msg") == "HEARTBEAT"
        for evt in events
    )
    assert "HEARTBEAT" not in (tmp_path / "am_patch.log").read_text()


def test_disabled_status_does_not_emit_json_heartbeat(tmp_path: Path) -> None:
    (
        _,
        policy_cls,
        _,
        _,
        _,
        _,
        build_startup_logger_and_ipc,
        status_cls,
    ) = _import_am_patch()
    policy = policy_cls()
    policy.current_log_symlink_enabled = False
    policy.json_out = True
    status = status_cls(enabled=False, interval_tty=0.01, interval_non_tty=0.01)
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
    events = [json.loads(line) for line in (tmp_path / "am_patch.jsonl").read_text().splitlines()]
    assert not any(evt.get("kind") == "HEARTBEAT" for evt in events)


def test_resolve_repo_root_timeout_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    *_, resolve_repo_root, _, consume_diag, _, _ = _import_am_patch()
    import subprocess

    def _boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=3)

    monkeypatch.setattr("am_patch.repo_root.subprocess.run", _boom)
    monkeypatch.chdir(tmp_path)
    assert resolve_repo_root(timeout_s=3) == tmp_path
    diagnostic = consume_diag()
    assert diagnostic is not None
    assert "repo-root fallback to Path.cwd()" in diagnostic
    assert "TimeoutExpired" in diagnostic
