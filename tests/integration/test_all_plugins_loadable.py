"""Integration test for loading all builtin plugins."""

from pathlib import Path

import pytest

from audiomason.core.loader import PluginLoader


class TestAllPluginsLoadable:
    """Test that all builtin plugins can be loaded."""

    def test_all_builtin_plugins_loadable(self):
        """Test that all builtin plugins load without errors."""
        # Find builtin plugins directory
        # Assuming this test runs from repo root or has audiomason installed
        try:
            import audiomason

            audiomason_path = Path(audiomason.__file__).parent
            builtin_plugins_dir = audiomason_path.parent / "plugins"
        except ImportError:
            # Fallback to relative path if not installed
            builtin_plugins_dir = Path(__file__).parent.parent.parent / "plugins"

        if not builtin_plugins_dir.exists():
            pytest.skip(f"Builtin plugins directory not found: {builtin_plugins_dir}")

        loader = PluginLoader(builtin_plugins_dir=builtin_plugins_dir)

        # Discover all plugins
        plugin_dirs = loader.discover()
        assert len(plugin_dirs) > 0, "No plugins found"

        # Track results
        loaded_plugins = []
        failed_plugins = []

        # Try to load each plugin
        for plugin_dir in plugin_dirs:
            plugin_name = plugin_dir.name
            try:
                # Load with validation disabled to avoid test dependencies
                plugin = loader.load_plugin(plugin_dir, validate=False)
                loaded_plugins.append(plugin_name)
                assert plugin is not None, f"Plugin {plugin_name} loaded as None"
            except Exception as e:
                failed_plugins.append((plugin_name, str(e)))

        # Report results
        print(f"\nOK Loaded plugins ({len(loaded_plugins)}):")
        for name in sorted(loaded_plugins):
            print(f"  - {name}")

        if failed_plugins:
            print(f"\nX Failed plugins ({len(failed_plugins)}):")
            for name, error in failed_plugins:
                print(f"  - {name}: {error}")

        # All plugins should load
        assert len(failed_plugins) == 0, f"Failed to load {len(failed_plugins)} plugins"

    def test_core_plugins_present(self):
        """Test that core plugins are present."""
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
        plugin_names = {p.name for p in plugin_dirs}

        # Core plugins that must exist
        core_plugins = {"cmd_interface", "tui", "daemon", "web_server"}

        for plugin_name in core_plugins:
            assert plugin_name in plugin_names, f"Core plugin '{plugin_name}' not found"

    def test_plugins_have_manifests(self):
        """Test that all plugins have valid plugin.yaml manifests."""
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

        for plugin_dir in plugin_dirs:
            manifest_path = plugin_dir / "plugin.yaml"
            assert manifest_path.exists(), f"Manifest missing for {plugin_dir.name}"

            # Try to load manifest
            manifest = loader._load_manifest(plugin_dir)
            assert manifest.name, f"Plugin {plugin_dir.name} has no name in manifest"
            assert manifest.version, f"Plugin {plugin_dir.name} has no version"
            assert manifest.entrypoint, f"Plugin {plugin_dir.name} has no entrypoint"
