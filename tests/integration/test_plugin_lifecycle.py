"""Integration tests for plugin lifecycle (load, run, unload)."""

import pytest

from audiomason.core.loader import PluginLoader


class TestPluginLifecycle:
    """Test plugin lifecycle: discovery -> validation -> loading -> running."""

    def test_plugin_discovery_phase(self, tmp_path):
        """Test plugin discovery phase."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create valid plugin
        valid_plugin = plugins_dir / "valid"
        valid_plugin.mkdir()
        (valid_plugin / "plugin.yaml").write_text(
            """
name: valid
version: 1.0.0
description: Valid plugin
author: Test
license: MIT
entrypoint: plugin:ValidPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (valid_plugin / "plugin.py").write_text(
            """
class ValidPlugin:
    pass
"""
        )

        # Create invalid plugin (no manifest)
        invalid_plugin = plugins_dir / "invalid"
        invalid_plugin.mkdir()
        (invalid_plugin / "plugin.py").write_text(
            """
class InvalidPlugin:
    pass
"""
        )

        # Create non-plugin directory
        (plugins_dir / "not_a_plugin").mkdir()

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)
        discovered = loader.discover()

        # Should only discover plugin with manifest
        assert len(discovered) == 1
        assert discovered[0].name == "valid"

    def test_plugin_validation_phase(self, tmp_path):
        """Test plugin validation phase."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create plugin with invalid entrypoint
        plugin_dir = plugins_dir / "bad_entrypoint"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            """
name: bad_entrypoint
version: 1.0.0
description: Bad entrypoint
author: Test
license: MIT
entrypoint: nonexistent:BadPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: basic
"""
        )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)

        # Should fail validation
        from audiomason.core.errors import PluginValidationError

        with pytest.raises(PluginValidationError):
            loader.load_plugin(plugin_dir, validate=True)

    def test_plugin_loading_phase(self, tmp_path):
        """Test plugin loading phase."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "loadable"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            """
name: loadable
version: 1.0.0
description: Loadable plugin
author: Test
license: MIT
entrypoint: plugin:LoadablePlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (plugin_dir / "plugin.py").write_text(
            """
class LoadablePlugin:
    def __init__(self):
        self.loaded = True
"""
        )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)
        plugin = loader.load_plugin(plugin_dir, validate=False)

        assert plugin is not None
        assert hasattr(plugin, "loaded")
        assert plugin.loaded is True

    def test_plugin_caching(self, tmp_path):
        """Test that loaded plugins are cached."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "cached"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            """
name: cached
version: 1.0.0
description: Cached plugin
author: Test
license: MIT
entrypoint: plugin:CachedPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (plugin_dir / "plugin.py").write_text(
            """
class CachedPlugin:
    def __init__(self):
        self.instance_id = id(self)
"""
        )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)

        # Load twice
        plugin1 = loader.load_plugin(plugin_dir, validate=False)
        plugin2 = loader.get_plugin("cached")

        # Should be same instance
        assert plugin1 is plugin2
        assert plugin1.instance_id == plugin2.instance_id

    def test_plugin_manifest_access(self, tmp_path):
        """Test accessing plugin manifest after loading."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "with_manifest"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            """
name: with_manifest
version: 2.0.0
description: Plugin with manifest
author: Test Author
license: MIT
entrypoint: plugin:ManifestPlugin
interfaces: [audio_processor]
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (plugin_dir / "plugin.py").write_text(
            """
class ManifestPlugin:
    pass
"""
        )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)
        loader.load_plugin(plugin_dir, validate=False)

        manifest = loader.get_manifest("with_manifest")
        assert manifest.name == "with_manifest"
        assert manifest.version == "2.0.0"
        assert manifest.author == "Test Author"
        assert "audio_processor" in manifest.interfaces

    def test_plugin_list(self, tmp_path):
        """Test listing all loaded plugins."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create multiple plugins
        for name in ["plugin1", "plugin2", "plugin3"]:
            plugin_dir = plugins_dir / name
            plugin_dir.mkdir()
            (plugin_dir / "plugin.yaml").write_text(
                f"""
name: {name}
version: 1.0.0
description: Test plugin {name}
author: Test
license: MIT
entrypoint: plugin:TestPlugin{name.upper()}
interfaces: []
hooks: []
dependencies: {{}}
config_schema: {{}}
test_level: none
"""
            )
            (plugin_dir / "plugin.py").write_text(
                f"""
class TestPlugin{name.upper()}:
    pass
"""
            )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)

        # Load all
        for plugin_dir in loader.discover():
            loader.load_plugin(plugin_dir, validate=False)

        # List should contain all three
        plugin_names = loader.list_plugins()
        assert len(plugin_names) == 3
        assert "plugin1" in plugin_names
        assert "plugin2" in plugin_names
        assert "plugin3" in plugin_names

    def test_plugin_not_found_error(self):
        """Test error when accessing non-existent plugin."""
        loader = PluginLoader()

        from audiomason.core.errors import PluginNotFoundError

        with pytest.raises(PluginNotFoundError):
            loader.get_plugin("nonexistent")

        with pytest.raises(PluginNotFoundError):
            loader.get_manifest("nonexistent")

    def test_plugin_with_imports(self, tmp_path):
        """Test plugin that imports standard library modules."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "with_imports"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            """
name: with_imports
version: 1.0.0
description: Plugin with imports
author: Test
license: MIT
entrypoint: plugin:ImportPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (plugin_dir / "plugin.py").write_text(
            """
import json
import pathlib
from typing import Any

class ImportPlugin:
    def __init__(self):
        self.json_module = json
        self.pathlib_module = pathlib

    def test_method(self) -> dict[str, Any]:
        return {"status": "ok"}
"""
        )

        loader = PluginLoader(builtin_plugins_dir=plugins_dir)
        plugin = loader.load_plugin(plugin_dir, validate=False)

        assert plugin is not None
        assert hasattr(plugin, "test_method")
        assert plugin.test_method() == {"status": "ok"}
