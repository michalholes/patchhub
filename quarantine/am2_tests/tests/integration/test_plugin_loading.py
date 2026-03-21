"""Integration tests for plugin auto-loading and discovery."""

from pathlib import Path

import pytest
from audiomason.core.loader import PluginLoader


class TestPluginAutoLoading:
    """Test automatic plugin discovery and loading."""

    def test_discover_builtin_plugins(self):
        """Test discovery of builtin plugins."""
        try:
            import audiomason

            audiomason_path = Path(audiomason.__file__).parent
            builtin_plugins_dir = audiomason_path.parent / "plugins"
        except ImportError:
            builtin_plugins_dir = Path(__file__).parent.parent.parent / "plugins"

        if not builtin_plugins_dir.exists():
            pytest.skip(f"Builtin plugins directory not found: {builtin_plugins_dir}")

        loader = PluginLoader(builtin_plugins_dir=builtin_plugins_dir)
        plugin_dirs = loader.discover()

        assert len(plugin_dirs) > 0, "No plugins discovered"
        assert any(p.name == "cmd_interface" for p in plugin_dirs), "CLI plugin not discovered"

    def test_discover_user_plugins(self, tmp_path):
        """Test discovery of user plugins."""
        # Create fake user plugin
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()

        fake_plugin_dir = user_plugins_dir / "test_plugin"
        fake_plugin_dir.mkdir()

        # Create minimal manifest
        manifest_path = fake_plugin_dir / "plugin.yaml"
        manifest_path.write_text(
            """
name: test_plugin
version: 1.0.0
description: Test plugin
author: Test
license: MIT
entrypoint: plugin:TestPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )

        # Create minimal plugin
        plugin_file = fake_plugin_dir / "plugin.py"
        plugin_file.write_text(
            """
class TestPlugin:
    def __init__(self):
        pass
"""
        )

        # Discover
        loader = PluginLoader(user_plugins_dir=user_plugins_dir)
        plugin_dirs = loader.discover()

        assert len(plugin_dirs) == 1, f"Expected 1 plugin, found {len(plugin_dirs)}"
        assert plugin_dirs[0].name == "test_plugin"

    def test_discover_system_plugins(self, tmp_path):
        """Test discovery of system plugins."""
        # Create fake system plugin
        system_plugins_dir = tmp_path / "system_plugins"
        system_plugins_dir.mkdir()

        fake_plugin_dir = system_plugins_dir / "system_test"
        fake_plugin_dir.mkdir()

        # Create minimal manifest
        manifest_path = fake_plugin_dir / "plugin.yaml"
        manifest_path.write_text(
            """
name: system_test
version: 1.0.0
description: System test plugin
author: Test
license: MIT
entrypoint: plugin:SystemTestPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )

        # Create minimal plugin
        plugin_file = fake_plugin_dir / "plugin.py"
        plugin_file.write_text(
            """
class SystemTestPlugin:
    def __init__(self):
        pass
"""
        )

        # Discover
        loader = PluginLoader(system_plugins_dir=system_plugins_dir)
        plugin_dirs = loader.discover()

        assert len(plugin_dirs) == 1
        assert plugin_dirs[0].name == "system_test"

    def test_discover_multiple_sources(self, tmp_path):
        """Test discovery from multiple plugin sources."""
        # Setup builtin
        try:
            import audiomason

            audiomason_path = Path(audiomason.__file__).parent
            builtin_plugins_dir = audiomason_path.parent / "plugins"
        except ImportError:
            builtin_plugins_dir = Path(__file__).parent.parent.parent / "plugins"

        # Setup user
        user_plugins_dir = tmp_path / "user"
        user_plugins_dir.mkdir()

        user_plugin = user_plugins_dir / "user_plugin"
        user_plugin.mkdir()
        (user_plugin / "plugin.yaml").write_text(
            """
name: user_plugin
version: 1.0.0
description: User plugin
author: Test
license: MIT
entrypoint: plugin:UserPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (user_plugin / "plugin.py").write_text(
            """
class UserPlugin:
    pass
"""
        )

        # Setup system
        system_plugins_dir = tmp_path / "system"
        system_plugins_dir.mkdir()

        system_plugin = system_plugins_dir / "system_plugin"
        system_plugin.mkdir()
        (system_plugin / "plugin.yaml").write_text(
            """
name: system_plugin
version: 1.0.0
description: System plugin
author: Test
license: MIT
entrypoint: plugin:SystemPlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
        )
        (system_plugin / "plugin.py").write_text(
            """
class SystemPlugin:
    pass
"""
        )

        # Discover all
        loader = PluginLoader(
            builtin_plugins_dir=builtin_plugins_dir if builtin_plugins_dir.exists() else None,
            user_plugins_dir=user_plugins_dir,
            system_plugins_dir=system_plugins_dir,
        )
        plugin_dirs = loader.discover()
        plugin_names = {p.name for p in plugin_dirs}

        assert "user_plugin" in plugin_names
        assert "system_plugin" in plugin_names

    def test_plugin_not_loaded_twice(self, tmp_path):
        """Test that same plugin from different sources isn't loaded twice."""
        # Create same plugin in two locations
        user_plugins_dir = tmp_path / "user"
        user_plugins_dir.mkdir()

        system_plugins_dir = tmp_path / "system"
        system_plugins_dir.mkdir()

        for base_dir in [user_plugins_dir, system_plugins_dir]:
            plugin_dir = base_dir / "duplicate"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.yaml").write_text(
                """
name: duplicate
version: 1.0.0
description: Duplicate plugin
author: Test
license: MIT
entrypoint: plugin:DuplicatePlugin
interfaces: []
hooks: []
dependencies: {}
config_schema: {}
test_level: none
"""
            )
            (plugin_dir / "plugin.py").write_text(
                """
class DuplicatePlugin:
    pass
"""
            )

        loader = PluginLoader(
            user_plugins_dir=user_plugins_dir,
            system_plugins_dir=system_plugins_dir,
        )

        plugin_dirs = loader.discover()

        # Should find both directories
        duplicate_plugins = [p for p in plugin_dirs if p.name == "duplicate"]
        assert len(duplicate_plugins) == 2, "Should discover both duplicate plugins"

        # But only one should be loadable (first one wins)
        loader.load_plugin(duplicate_plugins[0], validate=False)

        # Should have exactly one loaded
        assert len(loader.list_plugins()) == 1
        assert "duplicate" in loader.list_plugins()
