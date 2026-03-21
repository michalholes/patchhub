"""Unit tests for diagnostics_console CLI command.

These tests are intentionally narrow and rely on monkeypatching to avoid
filesystem I/O.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest


def test_help_lists_diag_command_with_origin(tmp_path: Path) -> None:
    from plugins.cmd_interface.plugin import CLIPlugin

    pdir = tmp_path / "diagnostics_console"
    pdir.mkdir(parents=True, exist_ok=True)

    (pdir / "plugin.yaml").write_text(
        "\n".join(
            [
                "name: diagnostics_console",
                'version: "0.0.1"',
                "description: test plugin",
                "author: test",
                "license: MIT",
                'entrypoint: "plugin:Dummy"',
                "interfaces:",
                "  - ICLICommands",
                "cli_commands:",
                "  - diag",
                "hooks: []",
                "dependencies: {}",
                "config_schema: {}",
                'test_level: "none"',
                "",
            ]
        )
    )

    help_text = CLIPlugin._build_help_for_tests([pdir])
    assert "diag    (plugin: diagnostics_console)" in help_text


def test_diag_on_off_calls_configservice(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    calls: list[tuple[str, str, object]] = []

    class FakeConfigService:
        def set_value(self, key_path: str, value: object) -> None:
            calls.append(("set", key_path, value))

        def unset_value(self, key_path: str) -> None:
            calls.append(("unset", key_path, None))

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigService",
        FakeConfigService,
    )

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    diag(["on"])
    diag(["off"])

    assert calls == [
        ("set", "diagnostics.enabled", True),
        ("unset", "diagnostics.enabled", None),
    ]


def test_diag_tail_no_follow_formats_events(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    class FakeFileService:
        def __init__(self) -> None:
            self._data = b"".join(
                [
                    (
                        b'{"event":"diag.job.start","component":"orchestration",'
                        b'"operation":"run_job","timestamp":"2026-02-11T12:00:00Z",'
                        b'"data":{"job_id":"J1","status":"running"}}'
                        b"\n"
                    ),
                    b"not-json\n",
                    (
                        b'{"event":"diag.job.end","component":"orchestration",'
                        b'"operation":"run_job","timestamp":"2026-02-11T12:00:01Z",'
                        b'"data":{"job_id":"J1","status":"succeeded"}}'
                        b"\n"
                    ),
                ]
            )

        @classmethod
        def from_resolver(cls, resolver):  # type: ignore[no-untyped-def]
            return cls()

        def exists(self, root, rel_path: str) -> bool:  # type: ignore[no-untyped-def]
            _ = root
            return rel_path == "diagnostics/diagnostics.jsonl"

        def open_read(self, root, rel_path: str):  # type: ignore[no-untyped-def]
            _ = root
            assert rel_path == "diagnostics/diagnostics.jsonl"
            return _FakeCtx(io.BytesIO(self._data))

    class _FakeCtx:
        def __init__(self, bio: io.BytesIO) -> None:
            self._bio = bio

        def __enter__(self) -> io.BytesIO:
            return self._bio

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.FileService",
        FakeFileService,
    )

    # Avoid reading real user/system config in tests.
    class FakeResolver:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, key: str):  # type: ignore[no-untyped-def]
            raise Exception(key)

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigResolver",
        FakeResolver,
    )

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    diag(["tail", "--no-follow", "--max-events", "10"])

    out = capsys.readouterr().out.splitlines()

    # Two valid events + one warning for invalid JSON.
    assert any("diag.job.start" in line for line in out)
    assert any("diag.job.end" in line for line in out)
    assert any(line.startswith("WARN:") for line in out)


def test_diag_help_flag_as_first_arg_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    rc = diag(["--help"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "audiomason diag" in out


def test_waiting_message_prints_once_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    class FakeFileService:
        def __init__(self) -> None:
            self._exists_calls = 0
            self._data = b"".join(
                [
                    (
                        b'{"event":"diag.test","component":"t","operation":"op",'
                        b'"timestamp":"2026-02-12T00:00:00Z","data":{}}'
                        b"\n"
                    ),
                    (
                        b'{"event":"diag.test","component":"t","operation":"op",'
                        b'"timestamp":"2026-02-12T00:00:00Z","data":{}}'
                        b"\n"
                    ),
                ]
            )

        @classmethod
        def from_resolver(cls, resolver):  # type: ignore[no-untyped-def]
            return cls()

        def exists(self, root, rel_path: str) -> bool:  # type: ignore[no-untyped-def]
            _ = root
            if rel_path != "diagnostics/diagnostics.jsonl":
                return False
            self._exists_calls += 1
            # Appear on 15th check (~3s at 0.2s sleep)
            return self._exists_calls >= 15

        def open_read(self, root, rel_path: str):  # type: ignore[no-untyped-def]
            _ = root
            _ = rel_path
            return _FakeCtx(io.BytesIO(self._data))

    class _FakeCtx:
        def __init__(self, bio: io.BytesIO) -> None:
            self._bio = bio

        def __enter__(self) -> io.BytesIO:
            return self._bio

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.FileService",
        FakeFileService,
    )

    class FakeResolver:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, key: str):  # type: ignore[no-untyped-def]
            if key == "diagnostics.console.wait_status_repeat":
                return False, "default"
            raise Exception(key)

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigResolver",
        FakeResolver,
    )

    # Deterministic time: advance by 0.2s per sleep.
    now = {"t": 0.0}

    def fake_time() -> float:
        return now["t"]

    def fake_sleep(_s: float) -> None:
        now["t"] += 0.2

    monkeypatch.setattr("plugins.diagnostics_console.plugin.time.time", fake_time)
    monkeypatch.setattr("plugins.diagnostics_console.plugin.time.sleep", fake_sleep)

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    rc = diag(["tail", "--max-events", "1"])
    assert rc == 0

    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines.count("waiting for diagnostics sink...") == 1


def test_waiting_message_repeats_when_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    class FakeFileService:
        def __init__(self) -> None:
            self._exists_calls = 0
            self._data = (
                b'{"event":"diag.test","component":"t","operation":"op",'
                b'"timestamp":"2026-02-12T00:00:00Z","data":{}}'
                b"\n"
            )

        @classmethod
        def from_resolver(cls, resolver):  # type: ignore[no-untyped-def]
            return cls()

        def exists(self, root, rel_path: str) -> bool:  # type: ignore[no-untyped-def]
            _ = root
            if rel_path != "diagnostics/diagnostics.jsonl":
                return False
            self._exists_calls += 1
            # Appear after enough time for repeated notices.
            return self._exists_calls >= 35  # ~7s

        def open_read(self, root, rel_path: str):  # type: ignore[no-untyped-def]
            _ = root
            _ = rel_path
            return _FakeCtx(io.BytesIO(self._data))

    class _FakeCtx:
        def __init__(self, bio: io.BytesIO) -> None:
            self._bio = bio

        def __enter__(self) -> io.BytesIO:
            return self._bio

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.FileService",
        FakeFileService,
    )

    class FakeResolver:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, key: str):  # type: ignore[no-untyped-def]
            if key == "diagnostics.console.wait_status_repeat":
                return True, "user_config"
            raise Exception(key)

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigResolver",
        FakeResolver,
    )

    now = {"t": 0.0}

    def fake_time() -> float:
        return now["t"]

    def fake_sleep(_s: float) -> None:
        now["t"] += 0.2

    monkeypatch.setattr("plugins.diagnostics_console.plugin.time.time", fake_time)
    monkeypatch.setattr("plugins.diagnostics_console.plugin.time.sleep", fake_sleep)

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    rc = diag(["tail", "--max-events", "1"])
    assert rc == 0

    out_lines = capsys.readouterr().out.splitlines()
    # One initial + repeated every ~2 seconds until exists becomes true.
    assert out_lines.count("waiting for diagnostics sink...") >= 3


def test_diag_mode_log_no_follow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    class FakeFileService:
        def __init__(self) -> None:
            self._log = b'{"level":"INFO","logger":"audiomason.web","message":"hello","ts":null}\n'

        @classmethod
        def from_resolver(cls, resolver):  # type: ignore[no-untyped-def]
            return cls()

        def exists(self, root, rel_path: str) -> bool:  # type: ignore[no-untyped-def]
            _ = root
            return rel_path == "logs/system.log"

        def open_read(self, root, rel_path: str):  # type: ignore[no-untyped-def]
            _ = root
            assert rel_path == "logs/system.log"
            return _FakeCtx(io.BytesIO(self._log))

    class _FakeCtx:
        def __init__(self, bio: io.BytesIO) -> None:
            self._bio = bio

        def __enter__(self) -> io.BytesIO:
            return self._bio

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.FileService",
        FakeFileService,
    )

    class FakeResolver:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, key: str):  # type: ignore[no-untyped-def]
            if key == "plugins.syslog.filename":
                return "logs/system.log", "default"
            if key == "plugins.syslog.disk_format":
                return "jsonl", "default"
            if key == "diagnostics.console.wait_status_repeat":
                return False, "default"
            raise Exception(key)

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigResolver",
        FakeResolver,
    )

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    rc = diag(["tail", "--no-follow", "--mode", "log"])
    assert rc == 0

    out_lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("LOG: ") for line in out_lines)
    info_lines = (
        "INFO" in line and "audiomason.web:" in line and "hello" in line for line in out_lines
    )
    assert any(info_lines)


def test_diag_mode_both_no_follow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin

    class FakeFileService:
        def __init__(self) -> None:
            self._events = (
                b'{"event":"diag.job.start","component":"orchestration",'
                b'"operation":"run_job","timestamp":"2026-02-11T12:00:00Z",'
                b'"data":{"job_id":"J1","status":"running"}}'
                b"\n"
            )
            self._log = b"INFO audiomason.web: hello\nplain line 1\n"

        @classmethod
        def from_resolver(cls, resolver):  # type: ignore[no-untyped-def]
            return cls()

        def exists(self, root, rel_path: str) -> bool:  # type: ignore[no-untyped-def]
            _ = root
            return rel_path in ("diagnostics/diagnostics.jsonl", "logs/system.log")

        def open_read(self, root, rel_path: str):  # type: ignore[no-untyped-def]
            _ = root
            if rel_path == "diagnostics/diagnostics.jsonl":
                return _FakeCtx(io.BytesIO(self._events))
            if rel_path == "logs/system.log":
                return _FakeCtx(io.BytesIO(self._log))
            raise AssertionError(rel_path)

    class _FakeCtx:
        def __init__(self, bio: io.BytesIO) -> None:
            self._bio = bio

        def __enter__(self) -> io.BytesIO:
            return self._bio

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.FileService",
        FakeFileService,
    )

    class FakeResolver:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, key: str):  # type: ignore[no-untyped-def]
            if key == "plugins.syslog.filename":
                return "logs/system.log", "default"
            if key == "plugins.syslog.disk_format":
                return "plain", "default"
            if key == "diagnostics.console.wait_status_repeat":
                return False, "default"
            raise Exception(key)

    monkeypatch.setattr(
        "plugins.diagnostics_console.plugin.ConfigResolver",
        FakeResolver,
    )

    plugin = DiagnosticsConsolePlugin()
    diag = plugin.get_cli_commands()["diag"]

    rc = diag(["tail", "--no-follow", "--mode", "both"])
    assert rc == 0

    out_lines = capsys.readouterr().out.splitlines()
    assert any("diag.job.start" in line for line in out_lines)
    assert any(line.startswith("LOG: ") for line in out_lines)
    info_lines = (
        "INFO" in line and "audiomason.web:" in line and "hello" in line for line in out_lines
    )
    assert any(info_lines)
