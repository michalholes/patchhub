from __future__ import annotations

import ast
from pathlib import Path

from .errors import RunnerError

_ALLOWED_CALLSITE = "gates_policy_wiring.py"


def _am_patch_dir_from_here() -> Path:
    return Path(__file__).resolve().parent


def _iter_py_files(am_patch_dir: Path) -> list[Path]:
    files = [p for p in am_patch_dir.rglob("*.py") if p.is_file()]
    return sorted(files, key=lambda p: str(p))


def _find_run_gates_calls(path: Path) -> list[int]:
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise RunnerError(
            "PREFLIGHT",
            "INTERNAL",
            f"non-utf8 python source in scripts/am_patch: {path}: {e}",
        ) from e

    try:
        mod = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        raise RunnerError(
            "PREFLIGHT",
            "INTERNAL",
            f"syntax error while scanning scripts/am_patch: {path}: {e}",
        ) from e

    out: list[int] = []
    for node in ast.walk(mod):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (
            isinstance(fn, ast.Name)
            and fn.id == "run_gates"
            or isinstance(fn, ast.Attribute)
            and fn.attr == "run_gates"
        ):
            out.append(int(getattr(node, "lineno", 0) or 0))
    return out


def assert_single_run_gates_callsite() -> None:
    am_patch_dir = _am_patch_dir_from_here()
    if not am_patch_dir.is_dir():
        raise RunnerError(
            "PREFLIGHT",
            "INTERNAL",
            f"missing am_patch directory at: {am_patch_dir}",
        )

    violations: list[tuple[str, int]] = []
    for py in _iter_py_files(am_patch_dir):
        rel = py.relative_to(am_patch_dir).as_posix()
        lines = _find_run_gates_calls(py)
        if not lines:
            continue
        if rel == _ALLOWED_CALLSITE:
            continue
        for ln in lines:
            violations.append((rel, ln if ln > 0 else 0))

    if violations:
        violations.sort(key=lambda t: (t[0], t[1]))
        detail = "\n".join([f"- am_patch/{p}:{ln}" for (p, ln) in violations])
        raise RunnerError(
            "PREFLIGHT",
            "INTERNAL",
            "run_gates call-sites must be centralized in am_patch/gates_policy_wiring.py\n"
            + detail,
        )
