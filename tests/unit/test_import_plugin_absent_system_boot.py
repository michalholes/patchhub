"""Issue 220: system should boot when the import plugin is absent."""

from __future__ import annotations

import shutil
from pathlib import Path

from audiomason.core.loader import PluginLoader


def test_loader_can_load_all_other_plugins_when_import_absent(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_plugins = repo_root / "plugins"

    dst_plugins = tmp_path / "plugins"
    shutil.copytree(src_plugins, dst_plugins)

    # Remove import plugin directory.
    shutil.rmtree(dst_plugins / "import")

    loader = PluginLoader(builtin_plugins_dir=dst_plugins)
    plugin_dirs = loader.discover()

    # Ensure import is not discovered.
    assert all(p.name != "import" for p in plugin_dirs)

    for d in plugin_dirs:
        loader.load_plugin(d, validate=False)

    names = set(loader.list_plugins())
    assert "import" not in names
