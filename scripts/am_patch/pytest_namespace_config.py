from __future__ import annotations

from collections.abc import Mapping, Sequence

PYTEST_ROOTS_DEFAULT = {
    "amp.*": "scripts/am_patch/",
    "am2.*": "src/audiomason/core/",
    "*": "*",
}

PYTEST_TREE_DEFAULT = {
    "amp.phb": "scripts/patchhub/",
    "amp.badguys": "badguys/",
    "am2.plugins": "plugins/",
    "am2.plugins.audio_processor": "plugins/audio_processor/",
    "am2.plugins.cmd_interface": "plugins/cmd_interface/",
    "am2.plugins.cover_handler": "plugins/cover_handler/",
    "am2.plugins.daemon": "plugins/daemon/",
    "am2.plugins.diagnostics_console": "plugins/diagnostics_console/",
    "am2.plugins.example_plugin": "plugins/example_plugin/",
    "am2.plugins.file_io": "plugins/file_io/",
    "am2.plugins.id3_tagger": "plugins/id3_tagger/",
    "am2.plugins.import": "plugins/import/",
    "am2.plugins.metadata_googlebooks": "plugins/metadata_googlebooks/",
    "am2.plugins.metadata_openlibrary": "plugins/metadata_openlibrary/",
    "am2.plugins.syslog": "plugins/syslog/",
    "am2.plugins.test_all_plugin": "plugins/test_all_plugin/",
    "am2.plugins.text_utils": "plugins/text_utils/",
    "am2.plugins.tui": "plugins/tui/",
    "am2.plugins.ui_rich": "plugins/ui_rich/",
    "am2.plugins.web_interface": "plugins/web_interface/",
}

PYTEST_NAMESPACE_MODULES_DEFAULT = {
    "amp": ["am_patch", "scripts.am_patch"],
    "amp.phb": ["patchhub", "scripts.patchhub"],
    "amp.badguys": ["badguys"],
    "am2": ["audiomason.core"],
    "am2.plugins": ["plugins"],
    "am2.plugins.audio_processor": ["plugins.audio_processor"],
    "am2.plugins.cmd_interface": ["plugins.cmd_interface"],
    "am2.plugins.cover_handler": ["plugins.cover_handler"],
    "am2.plugins.daemon": ["plugins.daemon"],
    "am2.plugins.diagnostics_console": ["plugins.diagnostics_console"],
    "am2.plugins.example_plugin": ["plugins.example_plugin"],
    "am2.plugins.file_io": ["plugins.file_io"],
    "am2.plugins.id3_tagger": ["plugins.id3_tagger"],
    "am2.plugins.import": ["plugins.import"],
    "am2.plugins.metadata_googlebooks": ["plugins.metadata_googlebooks"],
    "am2.plugins.metadata_openlibrary": ["plugins.metadata_openlibrary"],
    "am2.plugins.syslog": ["plugins.syslog"],
    "am2.plugins.test_all_plugin": ["plugins.test_all_plugin"],
    "am2.plugins.text_utils": ["plugins.text_utils"],
    "am2.plugins.tui": ["plugins.tui"],
    "am2.plugins.ui_rich": ["plugins.ui_rich"],
    "am2.plugins.web_interface": ["plugins.web_interface"],
}

PYTEST_DEPENDENCIES_DEFAULT = {
    "amp.phb": ["amp"],
    "amp.badguys": ["amp"],
    "am2.plugins.import": [
        "am2.plugins.file_io",
        "am2.plugins.cover_handler",
        "am2.plugins.metadata_openlibrary",
        "am2.plugins.audio_processor",
        "am2.plugins.id3_tagger",
    ],
    "am2.plugins.web_interface": [
        "am2.plugins.file_io",
        "am2.plugins.import",
    ],
    "am2.plugins.diagnostics_console": ["am2.plugins.file_io"],
    "am2.plugins.syslog": ["am2.plugins.file_io"],
    "am2.plugins.tui": ["am2.plugins.file_io"],
}

PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT = {
    "am2.plugins.import": [
        "am2.plugins.cmd_interface",
        "am2.plugins.daemon",
        "am2.plugins.diagnostics_console",
        "am2.plugins.metadata_googlebooks",
        "am2.plugins.syslog",
        "am2.plugins.text_utils",
        "am2.plugins.web_interface",
    ],
}

PYTEST_FULL_SUITE_PREFIXES_DEFAULT = [
    "pyproject.toml",
    "pytest.ini",
    "tests/conftest.py",
    "tests/e2e/conftest.py",
    "tests/e2e/_server_web_interface.py",
    "tests/e2e/_server_patchhub.py",
    "tests/e2e/_asset_inventory.py",
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


def _normalize_dependencies(
    raw: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
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
