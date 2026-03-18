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
    module_name = "am_patch_runner_test_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeLogger:
    def __init__(self, *, actions: list[str] | None = None) -> None:
        self.actions = actions if actions is not None else []
        self.debug_messages: list[str] = []
        self.control_events: list[dict[str, object]] = []
        self.close_calls = 0
        self._last_seq = 0

    def emit(self, **kwargs) -> None:
        self.actions.append("logger.emit")
        self.debug_messages.append(str(kwargs.get("message", "")))

    def emit_control_event(self, payload: dict[str, object], *, before_publish=None) -> int:
        self._last_seq += 1
        if callable(before_publish):
            before_publish(self._last_seq)
        self.actions.append(f"logger.control:{payload.get('event', '')}")
        self.control_events.append(dict(payload))
        return self._last_seq

    def get_last_json_seq(self) -> int:
        return self._last_seq

    def close(self) -> None:
        self.actions.append("logger.close")
        self.close_calls += 1


class _FakeIpc:
    def __init__(self, *, startup_done: bool, actions: list[str] | None = None) -> None:
        self.actions = actions if actions is not None else []
        self.startup_done = startup_done
        self.begin_calls: list[int] = []
        self.wait_calls = 0
        self.stop_calls = 0

    def startup_handshake_completed(self) -> bool:
        return self.startup_done

    def begin_shutdown_handshake(self, *, eos_seq: int) -> bool:
        self.actions.append(f"ipc.begin:{eos_seq}")
        self.begin_calls.append(eos_seq)
        return self.startup_done

    def wait_for_drain_ack(self) -> bool:
        self.actions.append("ipc.wait_for_drain_ack")
        self.wait_calls += 1
        return True

    def stop(self) -> None:
        self.actions.append("ipc.stop")
        self.stop_calls += 1


@pytest.mark.parametrize(
    ("mode", "test_mode"),
    [
        ("workspace", False),
        ("workspace", True),
        ("finalize", False),
        ("finalize_workspace", False),
    ],
)
def test_main_shutdown_handshake_runs_from_all_supported_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    test_mode: bool,
) -> None:
    mod = _load_runner_script_module()
    actions: list[str] = []
    logger = _FakeLogger(actions=actions)
    ipc = _FakeIpc(startup_done=True, actions=actions)
    cli = SimpleNamespace(mode=mode)
    policy = SimpleNamespace(
        ipc_socket_cleanup_delay_success_s=3,
        ipc_socket_cleanup_delay_failure_s=7,
        test_mode=test_mode,
    )
    ctx = SimpleNamespace(cli=cli, policy=policy, logger=logger, ipc=ipc)

    monkeypatch.setattr(
        mod, "build_effective_policy", lambda argv: (cli, policy, Path("cfg"), "cfg")
    )
    monkeypatch.setattr(mod, "build_paths_and_logger", lambda *args: ctx)
    monkeypatch.setattr(mod, "run_mode", lambda run_ctx: {"ok": True, "mode": run_ctx.cli.mode})

    def _finalize_and_report(run_ctx, result):
        actions.append("finalize_and_report")
        return 0

    monkeypatch.setattr(mod, "finalize_and_report", _finalize_and_report)

    rc = mod.main([])

    assert rc == 0
    assert logger.control_events == [{"type": "control", "event": "eos"}]
    assert ipc.begin_calls == [1]
    assert ipc.wait_calls == 1
    assert ipc.stop_calls == 1
    assert logger.close_calls == 1
    assert any("drain_ack" in msg for msg in logger.debug_messages)
    assert actions == [
        "finalize_and_report",
        "logger.emit",
        "ipc.begin:1",
        "logger.control:eos",
        "ipc.wait_for_drain_ack",
        "ipc.stop",
        "logger.close",
    ]


@pytest.mark.parametrize(("exit_code", "expected_delay"), [(0, 3.0), (2, 7.0)])
def test_main_falls_back_to_legacy_cleanup_delay_without_startup_ready(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    expected_delay: float,
) -> None:
    mod = _load_runner_script_module()
    actions: list[str] = []
    logger = _FakeLogger(actions=actions)
    ipc = _FakeIpc(startup_done=False, actions=actions)
    cli = SimpleNamespace(mode="workspace")
    policy = SimpleNamespace(
        ipc_socket_cleanup_delay_success_s=3,
        ipc_socket_cleanup_delay_failure_s=7,
        test_mode=False,
    )
    ctx = SimpleNamespace(cli=cli, policy=policy, logger=logger, ipc=ipc)
    waits: list[float] = []

    class _FakeEvent:
        def wait(self, seconds: float) -> bool:
            waits.append(float(seconds))
            return True

    monkeypatch.setattr(
        mod, "build_effective_policy", lambda argv: (cli, policy, Path("cfg"), "cfg")
    )
    monkeypatch.setattr(mod, "build_paths_and_logger", lambda *args: ctx)
    monkeypatch.setattr(mod, "run_mode", lambda run_ctx: {"ok": True, "mode": run_ctx.cli.mode})

    def _finalize_and_report(run_ctx, result):
        actions.append("finalize_and_report")
        return exit_code

    monkeypatch.setattr(mod, "finalize_and_report", _finalize_and_report)
    monkeypatch.setattr(mod.threading, "Event", _FakeEvent)

    rc = mod.main([])

    assert rc == exit_code
    assert logger.control_events == []
    assert ipc.begin_calls == []
    assert ipc.wait_calls == 0
    assert ipc.stop_calls == 1
    assert logger.close_calls == 1
    assert waits == [expected_delay]
    assert actions == [
        "finalize_and_report",
        "ipc.stop",
        "logger.close",
    ]
