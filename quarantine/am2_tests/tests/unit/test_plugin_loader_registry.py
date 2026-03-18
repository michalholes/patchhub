from __future__ import annotations

from pathlib import Path

import pytest

from audiomason.core.config_service import ConfigService
from audiomason.core.errors import PluginError
from audiomason.core.loader import PluginLoader
from audiomason.core.plugin_registry import PluginRegistry


def test_loader_respects_plugin_registry(tmp_path: Path) -> None:
    # Create isolated config where example_plugin is disabled.
    cfg_path = tmp_path / "config.yaml"
    cfg = ConfigService(user_config_path=cfg_path)
    reg = PluginRegistry(cfg)
    reg.set_enabled("example_plugin", enabled=False)

    repo_plugins_dir = Path(__file__).resolve().parents[2] / "plugins"
    loader = PluginLoader(builtin_plugins_dir=repo_plugins_dir, registry=reg)

    example_dir = repo_plugins_dir / "example_plugin"
    assert example_dir.is_dir()

    with pytest.raises(PluginError):
        loader.load_plugin(example_dir, validate=False)
