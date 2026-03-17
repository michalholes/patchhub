"""Integration tests for the builtin sample plugin: test_all_plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiomason.core.context import ProcessingContext
from audiomason.core.loader import PluginLoader


def _builtin_plugins_dir() -> Path:
    return Path(__file__).parent.parent.parent / "plugins"


@pytest.mark.asyncio
async def test_discovery_and_interface_methods(tmp_path):
    plugins_dir = _builtin_plugins_dir()
    loader = PluginLoader(builtin_plugins_dir=plugins_dir)

    discovered = loader.discover()
    assert any(p.name == "test_all_plugin" for p in discovered)

    plugin_dir = plugins_dir / "test_all_plugin"
    plugin = loader.load_plugin(plugin_dir, validate=False)
    manifest = loader.get_manifest("test_all_plugin")

    assert "IProcessor" in manifest.interfaces
    assert "ICLICommands" in manifest.interfaces

    src = tmp_path / "in.mp3"
    src.write_bytes(b"x")
    ctx = ProcessingContext(id="t1", source=src)

    ctx = await plugin.process(ctx)
    assert "test_all_plugin.process" in ctx.completed_steps
    assert any("test_all_plugin.process ran" in w for w in ctx.warnings)

    ctx = await plugin.enrich(ctx)
    assert ctx.final_metadata.get("test_all_plugin_enriched") is True

    data = await plugin.fetch({"x": 1})
    assert data["provider"] == "test_all_plugin"
    assert data["query"] == {"x": 1}
    assert data["ok"] is True
