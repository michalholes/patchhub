from __future__ import annotations

from pathlib import Path

from audiomason.core.loader import PluginLoader


def test_discovery_is_deterministic_by_directory_name(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)

    for name in ["zeta", "alpha", "beta"]:
        d = plugins_dir / name
        d.mkdir()
        (d / "plugin.yaml").write_text("", encoding="utf-8")

    loader = PluginLoader(
        builtin_plugins_dir=plugins_dir,
        user_plugins_dir=tmp_path / "user_plugins",
        system_plugins_dir=tmp_path / "system_plugins",
    )

    discovered = loader.discover()
    assert [p.name for p in discovered] == ["alpha", "beta", "zeta"]
