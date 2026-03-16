from __future__ import annotations

from pathlib import Path

import pytest

from am_patch.pytest_namespace_config import (
    PYTEST_DEPENDENCIES_DEFAULT,
    PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    PYTEST_NAMESPACE_MODULES_DEFAULT,
    PYTEST_ROOTS_DEFAULT,
    PYTEST_TREE_DEFAULT,
)
from am_patch.pytest_namespace_validator import validate_namespace_policy


def test_namespace_validator_accepts_standalone_shipped_policy() -> None:
    evidence = validate_namespace_policy(
        repo_root=Path(__file__).resolve().parents[1],
        pytest_roots=PYTEST_ROOTS_DEFAULT,
        pytest_tree=PYTEST_TREE_DEFAULT,
        pytest_namespace_modules=PYTEST_NAMESPACE_MODULES_DEFAULT,
        pytest_dependencies=PYTEST_DEPENDENCIES_DEFAULT,
        pytest_external_dependencies=PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    )
    assert evidence.repo_dependency_edges == {}
    assert evidence.external_overrides == {}


def test_namespace_validator_rejects_missing_tree_path() -> None:
    broken_tree = dict(PYTEST_TREE_DEFAULT)
    broken_tree["amp"] = "amp/does_not_exist/"
    with pytest.raises(ValueError, match="missing_tree_path:amp:amp/does_not_exist"):
        validate_namespace_policy(
            repo_root=Path(__file__).resolve().parents[1],
            pytest_roots=PYTEST_ROOTS_DEFAULT,
            pytest_tree=broken_tree,
            pytest_namespace_modules=PYTEST_NAMESPACE_MODULES_DEFAULT,
            pytest_dependencies=PYTEST_DEPENDENCIES_DEFAULT,
            pytest_external_dependencies=PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
        )


def test_namespace_validator_rejects_missing_namespace_module_mapping() -> None:
    broken_modules = dict(PYTEST_NAMESPACE_MODULES_DEFAULT)
    broken_modules.pop("amp")
    with pytest.raises(ValueError, match="missing_namespace_module_mapping:amp"):
        validate_namespace_policy(
            repo_root=Path(__file__).resolve().parents[1],
            pytest_roots=PYTEST_ROOTS_DEFAULT,
            pytest_tree=PYTEST_TREE_DEFAULT,
            pytest_namespace_modules=broken_modules,
            pytest_dependencies=PYTEST_DEPENDENCIES_DEFAULT,
            pytest_external_dependencies=PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
        )
