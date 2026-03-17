"""Integration tests for executing plugin-provided CLI commands.

These tests validate Phase 3 behavior:
- sync and async handler execution
- session-level failure isolation
- help path does not import plugin code (lazy import)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.cmd_interface.plugin import CLIPlugin


def _write_plugin_dir(
    base: Path,
    *,
    name: str,
    cmd: str,
    plugin_py: str,
) -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                "version: 0.1.0",
                "entrypoint: plugin:Plugin",
                "interfaces:",
                "  - ICLICommands",
                "cli_commands:",
                f"  - {cmd}",
                "test_level: none",
                "",
            ]
        )
    )

    (plugin_dir / "plugin.py").write_text(plugin_py)
    return plugin_dir


@pytest.mark.asyncio
async def test_execute_sync_handler(tmp_path, capsys):
    plugin_py = (
        "class Plugin:\n"
        "    def get_cli_commands(self):\n"
        "        def hello(argv):\n"
        "            print('SYNC:' + ','.join(argv))\n"
        "        return {'hello': hello}\n"
    )

    pdir = _write_plugin_dir(tmp_path, name="p1", cmd="hello", plugin_py=plugin_py)

    cli = CLIPlugin()
    code = await cli._execute_argv(["audiomason", "hello", "arg1"], plugin_dirs=[pdir])
    captured = capsys.readouterr()

    assert code == 0
    assert "SYNC:arg1" in captured.out


@pytest.mark.asyncio
async def test_execute_async_handler(tmp_path, capsys):
    plugin_py = (
        "import asyncio\n\n"
        "class Plugin:\n"
        "    def get_cli_commands(self):\n"
        "        async def hello(argv):\n"
        "            await asyncio.sleep(0)\n"
        "            print('ASYNC:' + ','.join(argv))\n"
        "        return {'hello': hello}\n"
    )

    pdir = _write_plugin_dir(tmp_path, name="p2", cmd="hello", plugin_py=plugin_py)

    cli = CLIPlugin()
    code = await cli._execute_argv(["audiomason", "hello", "arg1"], plugin_dirs=[pdir])
    captured = capsys.readouterr()

    assert code == 0
    assert "ASYNC:arg1" in captured.out


@pytest.mark.asyncio
async def test_failure_isolation(tmp_path, capsys):
    plugin_py = (
        "class Plugin:\n"
        "    def get_cli_commands(self):\n"
        "        def boom(argv):\n"
        "            raise RuntimeError('boom')\n"
        "        return {'boom': boom}\n"
    )

    pdir = _write_plugin_dir(tmp_path, name="p3", cmd="boom", plugin_py=plugin_py)

    cli = CLIPlugin()

    code1 = await cli._execute_argv(["audiomason", "boom"], plugin_dirs=[pdir])
    capsys.readouterr()

    code2 = await cli._execute_argv(["audiomason", "boom"], plugin_dirs=[pdir])
    out2 = capsys.readouterr()

    code3 = await cli._execute_argv(["audiomason", "version"], plugin_dirs=[pdir])
    out3 = capsys.readouterr()

    assert code1 != 0
    assert code2 != 0
    assert "Plugin failed for session" in (out2.err + out2.out)

    assert code3 == 0
    assert "AudioMason v2.0.0-alpha" in out3.out


@pytest.mark.asyncio
async def test_lazy_import_for_help_and_unavailable_annotation(tmp_path):
    plugin_py = "raise RuntimeError('import boom')\n"
    pdir = _write_plugin_dir(tmp_path, name="p4", cmd="bad", plugin_py=plugin_py)

    # Help must not import plugin code.
    help_text = CLIPlugin._build_help_for_tests([pdir])
    assert "bad" in help_text
    assert "(plugin: p4)" in help_text

    # Invocation must import and fail, then mark plugin commands unavailable.
    cli = CLIPlugin()
    code1 = await cli._execute_argv(["audiomason", "bad"], plugin_dirs=[pdir])
    assert code1 != 0

    updated_help = cli._format_usage(cli._plugin_cli_commands)
    assert "bad    (plugin: p4) [unavailable]" in updated_help
