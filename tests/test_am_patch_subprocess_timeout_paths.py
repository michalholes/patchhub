from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    from am_patch.config import Policy, build_policy
    from am_patch.engine import build_paths_and_logger
    from am_patch.errors import RunnerError

    return Policy, build_policy, build_paths_and_logger, RunnerError


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


def _runtime_snapshot():
    import am_patch.runtime as runtime_mod

    return runtime_mod, {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
    }


def _restore_runtime(runtime_mod, old: dict[str, object]) -> None:
    for key, value in old.items():
        setattr(runtime_mod, key, value)


def test_build_paths_and_logger_defaults_target_to_runner_root(tmp_path: Path) -> None:
    policy_cls, _, build_paths_and_logger, _ = _import_am_patch()
    runtime_mod, old = _runtime_snapshot()
    ctx = None
    try:
        policy = policy_cls()
        policy.repo_root = None
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "warning"
        policy.json_out = False
        policy.ipc_socket_enabled = False
        cli = SimpleNamespace(issue_id="1000", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("")
        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        expected_runner_root = Path(__file__).resolve().parent.parent / "amp"
        assert ctx.runner_root == expected_runner_root
        assert ctx.repo_root == expected_runner_root
        assert ctx.artifacts_root == expected_runner_root
        assert "repo-root fallback to Path.cwd()" not in ctx.log_path.read_text()
    finally:
        if ctx is not None:
            ctx.status.stop()
            ctx.logger.close()
        _restore_runtime(runtime_mod, old)


def test_build_paths_and_logger_breaks_active_tty_status_before_failure_dump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy_cls, _, build_paths_and_logger, _ = _import_am_patch()
    runtime_mod, old = _runtime_snapshot()
    events: list[tuple[str, str]] = []
    monkeypatch.setattr("am_patch.status.sys.stderr", _FakeTtyStderr(events))
    ctx = None
    try:
        policy = policy_cls()
        policy.target_repo_roots = [str(tmp_path)]
        policy.repo_root = str(tmp_path)
        policy.current_log_symlink_enabled = False
        policy.verbosity = "normal"
        policy.log_level = "quiet"
        policy.json_out = False
        policy.ipc_socket_enabled = False
        cli = SimpleNamespace(issue_id="1000", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("")
        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        ctx.status.set_stage("GATE_PYTEST")
        time.sleep(0.05)

        def _write_screen(s: str) -> None:
            events.append(("screen", s))

        ctx.logger._write_screen = _write_screen
        ctx.logger.run_logged(
            [
                "python3",
                "-c",
                "import sys; sys.stderr.write('boom\\n'); sys.stderr.flush(); raise SystemExit(1)",
            ]
        )
        first_screen_index = next(i for i, event in enumerate(events) if event[0] == "screen")
        assert any(
            kind == "stderr" and payload == "\n" for kind, payload in events[:first_screen_index]
        )
        screen_payloads = [payload for kind, payload in events if kind == "screen"]
        assert screen_payloads[0].startswith("\n" + ("=" * 80))
        assert any(payload == "[stderr]\n" for payload in screen_payloads)
        assert any("boom\n" in payload for payload in screen_payloads)
    finally:
        if ctx is not None:
            ctx.status.stop()
            ctx.logger.close()
        _restore_runtime(runtime_mod, old)


def test_build_policy_validates_runner_subprocess_timeout() -> None:
    policy_cls, build_policy, _, runner_error_cls = _import_am_patch()
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


def test_build_paths_and_logger_supports_cross_repo_target_and_artifacts_root(
    tmp_path: Path,
) -> None:
    policy_cls, _, build_paths_and_logger, _ = _import_am_patch()
    runtime_mod, old = _runtime_snapshot()
    ctx = None
    try:
        target_a = tmp_path / "target_a"
        target_b = tmp_path / "target_b"
        artifacts = tmp_path / "artifacts"
        target_a.mkdir()
        target_b.mkdir()
        artifacts.mkdir()
        policy = policy_cls()
        policy.target_repo_roots = [str(target_a), str(target_b)]
        policy.active_target_repo_root = str(target_b)
        policy.artifacts_root = str(artifacts)
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "quiet"
        cli = SimpleNamespace(issue_id="1001", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("")
        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        assert ctx.repo_root == target_b.resolve()
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
        _restore_runtime(runtime_mod, old)
