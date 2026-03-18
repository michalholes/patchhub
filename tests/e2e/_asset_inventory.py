from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]

_HTML_SCRIPT_RE = re.compile(r'<script\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
_JS_LOAD_RE = re.compile(r'loadScript\(\s*["\']([^"\']+\.js(?:\?[^"\']*)?)["\']')

OUT_OF_SCOPE_BY_USER_DECISION = "out_of_scope_by_user_decision"


def canonical_url_path(url: str) -> str:
    parts = urlsplit(str(url))
    return parts.path or str(url)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _html_script_paths(path: Path) -> set[str]:
    return {canonical_url_path(match) for match in _HTML_SCRIPT_RE.findall(_read(path))}


def _js_loaded_script_paths(path: Path) -> set[str]:
    return {canonical_url_path(match) for match in _JS_LOAD_RE.findall(_read(path))}


def active_web_interface_paths() -> set[str]:
    return _html_script_paths(REPO_ROOT / "plugins" / "web_interface" / "ui" / "index.html")


def active_import_ui_paths() -> set[str]:
    return _html_script_paths(REPO_ROOT / "plugins" / "import" / "ui" / "web" / "index.html")


def active_patchhub_main_paths() -> set[str]:
    index_paths = _html_script_paths(
        REPO_ROOT / "scripts" / "patchhub" / "templates" / "index.html"
    )
    bootstrap_paths = _js_loaded_script_paths(
        REPO_ROOT / "scripts" / "patchhub" / "static" / "patchhub_bootstrap.js"
    )
    app_paths = _js_loaded_script_paths(REPO_ROOT / "scripts" / "patchhub" / "static" / "app.js")
    return index_paths | bootstrap_paths | app_paths


def active_patchhub_debug_paths() -> set[str]:
    return _html_script_paths(REPO_ROOT / "scripts" / "patchhub" / "templates" / "debug.html")


def active_patchhub_all_paths() -> set[str]:
    return active_patchhub_main_paths() | active_patchhub_debug_paths()


def active_js_coverage_map() -> dict[str, str]:
    coverage: dict[str, str] = {}
    for path in sorted(active_web_interface_paths()):
        coverage[path] = "web_interface_e2e"
    for path in sorted(active_import_ui_paths()):
        coverage[path] = "import_ui_e2e"
    for path in sorted(active_patchhub_main_paths()):
        coverage[path] = "patchhub_main_e2e"
    for path in sorted(active_patchhub_debug_paths()):
        coverage[path] = "patchhub_debug_e2e"
    coverage["/static/patchhub_shell.js"] = OUT_OF_SCOPE_BY_USER_DECISION
    return coverage


def active_js_paths_in_scope() -> set[str]:
    return {
        path
        for path, scenario in active_js_coverage_map().items()
        if scenario != OUT_OF_SCOPE_BY_USER_DECISION
    }
