from __future__ import annotations

from collections.abc import Mapping, Sequence

PYTEST_ROOTS_DEFAULT = {
    "amp.*": "amp/am_patch/",
    "*": "*",
}

PYTEST_TREE_DEFAULT: dict[str, str] = {}

PYTEST_NAMESPACE_MODULES_DEFAULT = {
    "amp": ["am_patch"],
}

PYTEST_DEPENDENCIES_DEFAULT: dict[str, list[str]] = {}

PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT: dict[str, list[str]] = {}

PYTEST_FULL_SUITE_PREFIXES_DEFAULT = [
    "pyproject.toml",
    "pytest.ini",
    "tests/conftest.py",
]


def _normalize_path(value: str) -> str:
    return str(value).replace("\\", "/").lstrip("./")


def _normalize_prefix(value: str) -> str:
    text = _normalize_path(str(value).rstrip("/"))
    return text if text != "*" else "*"


def _matches_prefix(path: str, prefix: str) -> bool:
    norm_path = _normalize_path(path)
    norm_prefix = _normalize_prefix(prefix)
    if not norm_prefix:
        return False
    if norm_prefix == "*":
        return True
    return norm_path == norm_prefix or norm_path.startswith(norm_prefix + "/")


def _namespace_stem(namespace: str) -> str:
    text = str(namespace).strip()
    if text == "*":
        return "*"
    return text[:-2] if text.endswith(".*") else text


def _normalize_roots(raw: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for namespace, prefix in (raw or {}).items():
        ns = str(namespace).strip()
        pref = _normalize_prefix(str(prefix))
        if not ns or not pref:
            continue
        out[ns] = pref
    return out


def _normalize_tree(raw: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for namespace, prefix in (raw or {}).items():
        ns = _namespace_stem(str(namespace))
        pref = _normalize_prefix(str(prefix))
        if not ns or not pref or ns == "*":
            continue
        out[ns] = pref
    return out


def _normalize_dependencies(raw: Mapping[str, Sequence[str]] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for namespace, deps in (raw or {}).items():
        ns = _namespace_stem(str(namespace))
        if not ns or ns == "*" or not isinstance(deps, Sequence):
            continue
        cleaned: list[str] = []
        for dep in deps:
            item = _namespace_stem(str(dep))
            if not item or item == "*" or item in cleaned:
                continue
            cleaned.append(item)
        out[ns] = cleaned
    return out


def _normalize_full_suite_prefixes(raw: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for prefix in raw or []:
        item = _normalize_prefix(str(prefix))
        if item and item not in out:
            out.append(item)
    return out


def _root_namespaces(roots: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    for namespace in roots:
        stem = _namespace_stem(namespace)
        if stem != "*" and stem not in out:
            out.append(stem)
    return out


def _root_for_namespace(namespace: str, roots: Mapping[str, str]) -> str:
    ns = _namespace_stem(namespace)
    best = "*"
    best_len = -1
    for raw_namespace in roots:
        stem = _namespace_stem(raw_namespace)
        if stem == "*":
            continue
        if ns == stem or ns.startswith(stem + "."):
            length = len(stem)
            if length > best_len:
                best = stem
                best_len = length
    return best


def _namespace_contains(parent: str, child: str) -> bool:
    p = _namespace_stem(parent)
    c = _namespace_stem(child)
    if p == "*":
        return True
    return c == p or c.startswith(p + ".")


def _normalize_namespace_modules(
    raw: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for namespace, prefixes in (raw or {}).items():
        ns = _namespace_stem(str(namespace))
        if not ns or ns == "*" or not isinstance(prefixes, Sequence):
            continue
        cleaned: list[str] = []
        for prefix in prefixes:
            item = str(prefix).strip().strip(".")
            if item and item not in cleaned:
                cleaned.append(item)
        out[ns] = cleaned
    return out
