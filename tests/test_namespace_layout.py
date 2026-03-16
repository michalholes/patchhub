from __future__ import annotations

from am_patch.monolith_gate import _module_for_relpath, _module_to_rel_hint
from am_patch.pytest_namespace_config import (
    PYTEST_NAMESPACE_MODULES_DEFAULT,
    PYTEST_ROOTS_DEFAULT,
    PYTEST_TREE_DEFAULT,
)


def test_namespace_defaults_target_standalone_amp_layout() -> None:
    assert PYTEST_ROOTS_DEFAULT == {"amp.*": "amp/am_patch/", "*": "*"}
    assert PYTEST_TREE_DEFAULT == {}
    assert PYTEST_NAMESPACE_MODULES_DEFAULT == {"amp": ["am_patch"]}


def test_monolith_module_mapping_targets_amp_layout() -> None:
    assert _module_for_relpath("amp/am_patch/runtime.py") == "am_patch.runtime"
    assert _module_to_rel_hint("am_patch.runtime") == "amp/am_patch/runtime.py"
