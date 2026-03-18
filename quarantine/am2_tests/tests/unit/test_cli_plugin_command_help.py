"""Unit tests for CLI plugin command stub registry and deterministic help output."""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.cmd_interface.plugin import CLIPlugin

from audiomason.core.errors import PluginError


def _write_plugin_yaml(plugin_dir: Path, *, name: str, commands: list[str]) -> None:
    """Create a minimal plugin.yaml that is valid for manifest-only parsing."""
    plugin_dir.mkdir(parents=True, exist_ok=True)

    commands_yaml = "\n".join(f"  - {cmd}" for cmd in commands)

    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                'version: "0.0.1"',
                "description: test plugin",
                "author: test",
                "license: MIT",
                'entrypoint: "plugin:Dummy"',
                "interfaces:",
                "  - ICLICommands",
                "cli_commands:",
                commands_yaml,
                "hooks: []",
                "dependencies: {}",
                "config_schema: {}",
                'test_level: "none"',
                "",
            ]
        )
    )


def test_help_lists_plugin_commands_with_origin(tmp_path: Path) -> None:
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"

    _write_plugin_yaml(p1, name="p1", commands=["hello"])
    _write_plugin_yaml(p2, name="p2", commands=["world"])

    help_text = CLIPlugin._build_help_for_tests([p1, p2])

    assert "hello    (plugin: p1)" in help_text
    assert "world    (plugin: p2)" in help_text


def test_collision_fails_deterministically(tmp_path: Path) -> None:
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"

    _write_plugin_yaml(p1, name="p1", commands=["dup"])
    _write_plugin_yaml(p2, name="p2", commands=["dup"])

    cli = CLIPlugin()
    with pytest.raises(PluginError) as excinfo:
        cli._build_plugin_cli_stub_registry(plugin_dirs=[p1, p2])

    assert "dup" in str(excinfo.value)


def test_shadowing_core_command_fails(tmp_path: Path) -> None:
    p1 = tmp_path / "p1"

    _write_plugin_yaml(p1, name="p1", commands=["process"])

    cli = CLIPlugin()
    with pytest.raises(PluginError) as excinfo:
        cli._build_plugin_cli_stub_registry(plugin_dirs=[p1])

    assert "process" in str(excinfo.value)


def test_registry_does_not_globally_sort_discovered_across_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When plugin_dirs is None, preserve PluginLoader.discover() iteration order.

    This asserts that the CLI host does not globally re-sort the combined discovered
    plugin directory list across sources (builtin/user/system).
    """

    import plugins.cmd_interface.plugin as cli_mod

    calls: list[Path] = []

    p2 = tmp_path / "zz_source"
    p1 = tmp_path / "aa_source"

    class FakeConfigService:
        pass

    class FakePluginRegistry:
        def __init__(self, cfg: FakeConfigService) -> None:
            self._cfg = cfg

        def is_enabled(self, plugin_name: str) -> bool:
            return True

    class FakePluginLoader:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def discover(self) -> list[Path]:
            return [p2, p1]

        def load_manifest_only(self, plugin_dir: Path):
            calls.append(plugin_dir)
            name = "p2" if plugin_dir == p2 else "p1"
            return type(
                "M",
                (),
                {
                    "name": name,
                    "interfaces": ["ICLICommands"],
                    "cli_commands": [f"cmd-{name}"],
                },
            )()

    monkeypatch.setattr(cli_mod, "ConfigService", FakeConfigService)
    monkeypatch.setattr(cli_mod, "PluginRegistry", FakePluginRegistry)
    monkeypatch.setattr(cli_mod, "PluginLoader", FakePluginLoader)

    cli = cli_mod.CLIPlugin()
    _ = cli._build_plugin_cli_stub_registry(plugin_dirs=None)

    assert calls == [p2, p1]
