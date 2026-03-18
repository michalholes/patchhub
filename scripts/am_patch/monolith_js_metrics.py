from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .monolith_gate import FileMetrics, MonolithAreas

import re
from pathlib import Path


def js_metrics(
    *,
    relpath: str,
    new_text: str,
    cwd: Path,
    repo_root: Path,
    areas: Sequence[MonolithAreas],
    compute_fanin: bool,
) -> FileMetrics:
    """Compute monolith metrics for JavaScript without external parsers.

    This module is intentionally heuristic and deterministic.
    Any error must be represented as parse_ok=False by the caller.
    """

    # Local import to avoid import cycles: monolith_gate imports this module.
    from .monolith_gate import FileMetrics, MonolithAreas, area_for_relpath

    _ = compute_fanin  # reserved for future parity with Python fan graphs

    try:
        area_rules: list[MonolithAreas] = [a for a in areas if isinstance(a, MonolithAreas)]

        loc = _count_loc(new_text)
        exports = _count_js_exports(new_text)
        targets = _resolve_internal_import_targets(
            relpath=relpath,
            text=new_text,
            cwd=cwd,
            repo_root=repo_root,
        )

        imported_areas = {
            area_for_relpath(tgt, area_rules)
            for tgt in targets
            if area_for_relpath(tgt, area_rules) != "other"
        }

        return FileMetrics(
            loc=loc,
            exports=exports,
            internal_imports=len(targets),
            distinct_areas=len(imported_areas),
            fanin=None,
            fanout=None,
            parse_ok=True,
        )
    except Exception:
        return FileMetrics(
            loc=_count_loc(new_text),
            exports=0,
            internal_imports=0,
            distinct_areas=0,
            fanin=None,
            fanout=None,
            parse_ok=False,
        )


_RE_EXPORT_LINE = re.compile(r"^\s*export\s+", re.MULTILINE)
_RE_EXPORTS_DOT = re.compile(r"\bexports\.([A-Za-z0-9_$]+)")
_RE_IMPORT_FROM = re.compile(r"\bimport\b[^;\n]*\bfrom\s*[\"']([^\"']+)[\"']")
_RE_EXPORT_FROM = re.compile(r"\bexport\b[^;\n]*\bfrom\s*[\"']([^\"']+)[\"']")
_RE_REQUIRE = re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)")


def js_internal_import_targets(
    *,
    relpath: str,
    text: str,
    cwd: Path,
    repo_root: Path,
) -> set[str]:
    """Return repo-relative internal JS import targets for relpath.

    This is a deterministic heuristic used by both the monolith gate and js_metrics().
    """
    return _resolve_internal_import_targets(
        relpath=relpath,
        text=text,
        cwd=cwd,
        repo_root=repo_root,
    )


def _norm_relpath(p: str) -> str:
    s = str(p).replace("\\\\", "/").strip()
    if s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _count_loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _count_js_exports(text: str) -> int:
    # ESM export statements
    export_lines = len(_RE_EXPORT_LINE.findall(text))

    # CJS module.exports occurrences
    module_exports = text.count("module.exports")

    # CJS exports.<name> distinct names
    names = {m.group(1) for m in _RE_EXPORTS_DOT.finditer(text)}
    return export_lines + module_exports + len(names)


def _iter_internal_specs(text: str) -> list[str]:
    specs: list[str] = []

    def add(spec: str) -> None:
        s = str(spec).strip()
        if not s or s in specs:
            return
        specs.append(s)

    for rx in (_RE_IMPORT_FROM, _RE_EXPORT_FROM, _RE_REQUIRE):
        for m in rx.finditer(text):
            add(m.group(1))

    return specs


def _resolve_spec_to_relpath(
    *,
    relpath: str,
    spec: str,
    cwd: Path,
    repo_root: Path,
) -> str | None:
    s = str(spec).strip()
    if not (s.startswith("./") or s.startswith("../")):
        return None

    # Drop query/fragment suffixes deterministically.
    for sep in ("?", "#"):
        if sep in s:
            s = s.split(sep, 1)[0]

    base = Path(_norm_relpath(relpath)).parent
    raw = (base / s).as_posix()
    cand = Path(_norm_relpath(raw))

    def exists(p: Path) -> bool:
        rp = _norm_relpath(str(p))
        return (cwd / rp).exists() or (repo_root / rp).exists()

    if cand.suffix == ".js":
        return _norm_relpath(str(cand)) if exists(cand) else None

    c1 = Path(str(cand) + ".js")
    if exists(c1):
        return _norm_relpath(str(c1))
    c2 = cand / "index.js"
    if exists(c2):
        return _norm_relpath(str(c2))
    return None


def _resolve_internal_import_targets(
    *,
    relpath: str,
    text: str,
    cwd: Path,
    repo_root: Path,
) -> set[str]:
    targets: set[str] = set()
    for spec in _iter_internal_specs(text):
        tgt = _resolve_spec_to_relpath(
            relpath=relpath,
            spec=spec,
            cwd=cwd,
            repo_root=repo_root,
        )
        if tgt:
            targets.add(tgt)
    return targets
