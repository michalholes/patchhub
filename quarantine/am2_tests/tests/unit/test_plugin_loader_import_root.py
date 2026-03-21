from __future__ import annotations

import sys
from pathlib import Path

from audiomason.core.loader import PluginLoader


def test_loader_adds_repo_root_for_builtin_plugins_package(tmp_path: Path) -> None:
    repo_root = tmp_path
    plugins_dir = repo_root / "plugins"
    plugins_dir.mkdir(parents=True)

    # Mark 'plugins/' as a package so 'import plugins.*' is valid once repo_root is on sys.path.
    (plugins_dir / "__init__.py").write_text("", encoding="utf-8")

    # A dependency module importable as 'plugins.dep'
    (plugins_dir / "dep.py").write_text("VALUE = 1\n", encoding="utf-8")

    # Minimal plugin that performs a top-level import via 'plugins.*'
    plugin_dir = plugins_dir / "tp"
    plugin_dir.mkdir()

    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                "name: tp",
                "version: 0.0.0",
                "entrypoint: plugin:TestPlugin",
                "test_level: none",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "import plugins.dep",
                "",
                "class TestPlugin:",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )

    original_sys_path = list(sys.path)
    original_plugins_modules = {
        k: v for k, v in sys.modules.items() if k == "plugins" or k.startswith("plugins.")
    }

    try:
        # Simulate running via an installed entrypoint where repo_root is not on sys.path.
        sys.path = [p for p in sys.path if p != str(repo_root)]

        # Ensure any previously imported real 'plugins' package cannot mask the tmp_path package.
        for key in [k for k in list(sys.modules) if k == "plugins" or k.startswith("plugins.")]:
            del sys.modules[key]
        loader = PluginLoader(
            builtin_plugins_dir=plugins_dir,
            user_plugins_dir=tmp_path / "user_plugins",
            system_plugins_dir=tmp_path / "system_plugins",
        )
        loader.load_plugin(plugin_dir, validate=False)

        # Loader must add repo_root exactly once, deterministically.
        assert sys.path.count(str(repo_root)) == 1
        assert sys.path[0] == str(repo_root)
    finally:
        # Restore sys.modules to avoid leaking temporary packages into other tests.
        for key in [k for k in list(sys.modules) if k == "plugins" or k.startswith("plugins.")]:
            del sys.modules[key]
        sys.modules.update(original_plugins_modules)
        sys.path = original_sys_path
