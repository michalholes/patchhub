"""Integration tests for CLI execution of test_all_plugin commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.cmd_interface.plugin import CLIPlugin


def _test_all_plugin_dir() -> Path:
    return Path(__file__).parent.parent.parent / "plugins" / "test_all_plugin"


@pytest.mark.asyncio
async def test_cli_test_all(capsys):
    plugin_dir = _test_all_plugin_dir()
    cli = CLIPlugin()

    code = await cli._execute_argv(["audiomason", "test-all"], plugin_dirs=[plugin_dir])
    captured = capsys.readouterr()

    assert code == 0
    assert "OK:test-all" in captured.out


@pytest.mark.asyncio
async def test_cli_test_echo(capsys):
    plugin_dir = _test_all_plugin_dir()
    cli = CLIPlugin()

    code = await cli._execute_argv(
        ["audiomason", "test-echo", "a", "b"],
        plugin_dirs=[plugin_dir],
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "ECHO:a b" in captured.out
