from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import RunnerError
from .pytest_namespace_config import (
    PYTEST_DEPENDENCIES_DEFAULT,
    PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    PYTEST_FULL_SUITE_PREFIXES_DEFAULT,
    PYTEST_NAMESPACE_MODULES_DEFAULT,
    PYTEST_ROOTS_DEFAULT,
    PYTEST_TREE_DEFAULT,
    _normalize_dependencies,
    _normalize_namespace_modules,
)
from .pytest_namespace_routing import select_namespace_pytest_targets


def _mapping_dict_str(mapping: Mapping[str, object], key: str) -> dict[str, str]:
    raw = mapping.get(key, {})
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for item_key, item_value in raw.items():
        skey = str(item_key).strip()
        sval = str(item_value).strip()
        if skey and sval:
            out[skey] = sval
    return out


def _mapping_dict_list(mapping: Mapping[str, object], key: str) -> dict[str, list[str]]:
    raw = mapping.get(key, {})
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, list[str]] = {}
    for item_key, item_value in raw.items():
        skey = str(item_key).strip()
        if not skey or not isinstance(item_value, list):
            continue
        values = [str(item).strip() for item in item_value if str(item).strip()]
        out[skey] = values
    return out


def _mapping_list(mapping: Mapping[str, object], key: str) -> list[str]:
    raw = mapping.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def select_pytest_targets(
    *,
    decision_paths: Sequence[str],
    pytest_targets: Sequence[str],
    routing_policy: Mapping[str, object] | None,
) -> list[str]:
    if not routing_policy:
        return list(pytest_targets)

    mode = str(routing_policy.get("pytest_routing_mode", "legacy")).strip() or "legacy"
    if mode == "legacy":
        return list(pytest_targets)
    if mode != "bucketed":
        raise RunnerError(
            "CONFIG",
            "INVALID_PYTEST_ROUTING_MODE",
            f"invalid pytest_routing_mode: {mode!r}",
        )

    pytest_roots = _mapping_dict_str(routing_policy, "pytest_roots")
    pytest_tree = _mapping_dict_str(routing_policy, "pytest_tree")
    pytest_namespace_modules = _normalize_namespace_modules(
        _mapping_dict_list(routing_policy, "pytest_namespace_modules")
    )
    pytest_dependencies = _normalize_dependencies(
        _mapping_dict_list(routing_policy, "pytest_dependencies")
    )
    pytest_external_dependencies = _normalize_dependencies(
        _mapping_dict_list(routing_policy, "pytest_external_dependencies")
    )
    pytest_full_suite_prefixes = _mapping_list(routing_policy, "pytest_full_suite_prefixes")

    return select_namespace_pytest_targets(
        decision_paths=decision_paths,
        pytest_targets=pytest_targets,
        pytest_roots=pytest_roots or PYTEST_ROOTS_DEFAULT,
        pytest_tree=pytest_tree or PYTEST_TREE_DEFAULT,
        pytest_namespace_modules=(pytest_namespace_modules or PYTEST_NAMESPACE_MODULES_DEFAULT),
        pytest_dependencies=pytest_dependencies or PYTEST_DEPENDENCIES_DEFAULT,
        pytest_external_dependencies=(
            pytest_external_dependencies or PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT
        ),
        pytest_full_suite_prefixes=(
            pytest_full_suite_prefixes or PYTEST_FULL_SUITE_PREFIXES_DEFAULT
        ),
    )
