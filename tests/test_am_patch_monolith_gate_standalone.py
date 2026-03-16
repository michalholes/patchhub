from __future__ import annotations

import tomllib
from pathlib import Path

from am_patch.config_monolith_areas import parse_monolith_areas
from am_patch.monolith_gate import (
    _areas_from_policy,
    _module_for_relpath,
    _module_to_rel_hint,
    area_for_relpath,
)


def _shipped_monolith_policy() -> tuple[list[str], list[str], list[str]]:
    config_path = Path(__file__).resolve().parents[1] / "amp" / "am_patch.toml"
    data = tomllib.loads(config_path.read_text())
    monolith = data["monolith"]
    return parse_monolith_areas(monolith)


def test_monolith_module_mapping_targets_amp_layout() -> None:
    assert _module_for_relpath("amp/am_patch/runtime.py") == "am_patch.runtime"
    assert _module_to_rel_hint("am_patch.runtime") == "amp/am_patch/runtime.py"


def test_monolith_area_mapping_matches_standalone_shipped_config() -> None:
    prefixes, names, dynamic = _shipped_monolith_policy()
    areas = _areas_from_policy(prefixes, names, dynamic)
    assert area_for_relpath("amp/am_patch/runtime.py", areas) == "amp"
    assert area_for_relpath("tests/test_runtime_layout.py", areas) == "tests"
    assert area_for_relpath("amp/am_patch.py", areas) == "runner"
