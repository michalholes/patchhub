from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


class _FakeIpcController:
    wait_for_ready_result = True
    startup_handshake_completed_result = False

    def __init__(
        self,
        *,
        socket_path: Path,
        issue_id: str | None,
        mode: str,
        status_provider: Any,
        logger: Any,
        handshake_enabled: bool = False,
        handshake_wait_s: int = 0,
    ) -> None:
        self.socket_path = socket_path
        self.issue_id = issue_id
        self.mode = mode
        self.status_provider = status_provider
        self.logger = logger
        self.handshake_enabled = handshake_enabled
        self.handshake_wait_s = handshake_wait_s
        self.events: list[dict[str, Any]] = []
        self.calls: list[str] = []
        logger.set_ipc_stream(self.events.append)

    def start(self) -> None:
        self.calls.append("start")
        return None

    def stop(self) -> None:
        return None

    def wait_for_ready(self) -> bool:
        self.calls.append("wait_for_ready")
        return bool(type(self).wait_for_ready_result)

    def startup_handshake_completed(self) -> bool:
        return bool(type(self).startup_handshake_completed_result)

    def check_boundary(self, *, completed_step: str) -> str | None:
        return None

    def wait_if_paused(self) -> None:
        return None

    def snapshot(self) -> dict[str, Any]:
        return {"cancel": False}


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.engine as engine_mod
    import am_patch.engine_startup_runtime as startup_mod
    import am_patch.runtime as runtime_mod
    from am_patch.config import Policy as PolicyCls

    return PolicyCls, engine_mod, startup_mod, runtime_mod


def test_ipc_receives_start_and_hello_before_runtime_work(tmp_path: Path) -> None:
    policy_cls, engine_mod, startup_mod, runtime_mod = _import_am_patch()

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
        "resolve_socket_path": startup_mod.resolve_socket_path,
        "IpcController": startup_mod.IpcController,
    }

    ctx = None
    try:
        startup_mod.resolve_socket_path = lambda *, policy, patch_dir, issue_id: (
            patch_dir / "am_patch_issue_501.sock"
        )
        startup_mod.IpcController = _FakeIpcController

        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2"]
        policy.patch_dir = str(tmp_path / "patches")
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "quiet"
        policy.json_out = False

        cli = SimpleNamespace(issue_id="501", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = engine_mod.build_paths_and_logger(cli, policy, cfg, "test")
        assert ctx.ipc is not None
        assert [event["type"] for event in ctx.ipc.events[:2]] == ["log", "hello"]
        assert ctx.ipc.events[0]["kind"] == "START"
        assert ctx.ipc.events[1]["issue_id"] == "501"
        assert ctx.ipc.events[1]["runner_mode"] == "workspace"
    finally:
        if ctx is not None:
            if ctx.ipc is not None:
                ctx.ipc.stop()
            ctx.status.stop()
            ctx.logger.close()
        startup_mod.resolve_socket_path = old["resolve_socket_path"]
        startup_mod.IpcController = old["IpcController"]
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


def test_ipc_waits_for_ready_before_start_and_hello(tmp_path: Path) -> None:
    policy_cls, engine_mod, startup_mod, runtime_mod = _import_am_patch()

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
        "resolve_socket_path": startup_mod.resolve_socket_path,
        "IpcController": startup_mod.IpcController,
    }

    ctx = None
    try:
        startup_mod.resolve_socket_path = lambda *, policy, patch_dir, issue_id: (
            patch_dir / "am_patch_issue_777.sock"
        )
        startup_mod.IpcController = _FakeIpcController

        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2"]
        policy.patch_dir = str(tmp_path / "patches")
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "quiet"
        policy.json_out = False
        policy.ipc_handshake_enabled = True
        policy.ipc_handshake_wait_s = 2

        cli = SimpleNamespace(issue_id="777", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = engine_mod.build_paths_and_logger(cli, policy, cfg, "test")
        assert ctx.ipc is not None
        assert ctx.ipc.calls[:2] == ["start", "wait_for_ready"]
        assert [event["type"] for event in ctx.ipc.events[:3]] == [
            "log",
            "hello",
            "log",
        ]
        assert ctx.ipc.events[2]["sev"] == "DEBUG"
    finally:
        if ctx is not None:
            if ctx.ipc is not None:
                ctx.ipc.stop()
            ctx.status.stop()
            ctx.logger.close()
        startup_mod.resolve_socket_path = old["resolve_socket_path"]
        startup_mod.IpcController = old["IpcController"]
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


@pytest.mark.parametrize(
    ("verbosity", "log_level", "expect_human_debug"),
    [
        ("verbose", "verbose", False),
        ("debug", "debug", True),
    ],
)
def test_ipc_handshake_timeout_is_fail_open_and_human_debug_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verbosity: str,
    log_level: str,
    expect_human_debug: bool,
) -> None:
    policy_cls, engine_mod, startup_mod, runtime_mod = _import_am_patch()

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
        "resolve_socket_path": startup_mod.resolve_socket_path,
        "IpcController": startup_mod.IpcController,
    }

    ctx = None
    old_wait = _FakeIpcController.wait_for_ready_result
    try:
        _FakeIpcController.wait_for_ready_result = False
        startup_mod.resolve_socket_path = lambda *, policy, patch_dir, issue_id: (
            patch_dir / "am_patch_issue_778.sock"
        )
        startup_mod.IpcController = _FakeIpcController

        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2"]
        policy.patch_dir = str(tmp_path / "patches")
        policy.current_log_symlink_enabled = False
        policy.verbosity = verbosity
        policy.log_level = log_level
        policy.json_out = False
        policy.ipc_handshake_enabled = True
        policy.ipc_handshake_wait_s = 2

        cli = SimpleNamespace(issue_id="778", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = engine_mod.build_paths_and_logger(cli, policy, cfg, "test")
        assert ctx.ipc is not None
        assert ctx.ipc.calls[:2] == ["start", "wait_for_ready"]
        assert [event["type"] for event in ctx.ipc.events[:3]] == [
            "log",
            "hello",
            "log",
        ]
        assert ctx.ipc.events[0]["kind"] == "START"
        assert ctx.ipc.events[2]["msg"] == (
            "DEBUG: IPC startup handshake timed out; continuing legacy IPC"
        )

        screen = capsys.readouterr().out
        log_text = ctx.log_path.read_text(encoding="utf-8")
        needle = "DEBUG: IPC startup handshake timed out; continuing legacy IPC"
        assert (needle in screen) is expect_human_debug
        assert (needle in log_text) is expect_human_debug
    finally:
        _FakeIpcController.wait_for_ready_result = old_wait
        if ctx is not None:
            if ctx.ipc is not None:
                ctx.ipc.stop()
            ctx.status.stop()
            ctx.logger.close()
        startup_mod.resolve_socket_path = old["resolve_socket_path"]
        startup_mod.IpcController = old["IpcController"]
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
