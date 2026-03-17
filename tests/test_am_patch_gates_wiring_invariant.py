from __future__ import annotations

import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _iter_py_files(am_patch_dir: Path) -> list[Path]:
    files = [p for p in am_patch_dir.rglob("*.py") if p.is_file()]
    return sorted(files, key=lambda p: str(p))


def _find_run_gates_calls(path: Path) -> list[int]:
    src = path.read_text(encoding="utf-8")
    mod = ast.parse(src, filename=str(path))

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


def test_single_run_gates_callsite_in_scripts_am_patch() -> None:
    repo_root = _repo_root()
    am_patch_dir = repo_root / "scripts" / "am_patch"
    assert am_patch_dir.is_dir(), f"missing am_patch dir: {am_patch_dir}"

    allowed = "scripts/am_patch/gates_policy_wiring.py"

    found: list[str] = []
    for py in _iter_py_files(am_patch_dir):
        rel = py.relative_to(repo_root).as_posix()
        lines = _find_run_gates_calls(py)
        if not lines:
            continue
        for ln in lines:
            found.append(f"{rel}:{ln}")

    assert found, "expected at least one run_gates call-site"

    bad = [x for x in found if not x.startswith(allowed + ":")]
    assert not bad, "unexpected run_gates call-sites:\n" + "\n".join(sorted(bad))


def test_pytest_bucket_routing_external_callsite_is_only_gates_py() -> None:
    repo_root = _repo_root()
    am_patch_dir = repo_root / "scripts" / "am_patch"

    hits: list[str] = []
    for py in _iter_py_files(am_patch_dir):
        rel = py.relative_to(repo_root).as_posix()
        if rel == "scripts/am_patch/pytest_bucket_routing.py":
            continue
        src = py.read_text(encoding="utf-8")
        if "select_pytest_targets(" not in src:
            continue
        hits.append(rel)

    assert hits == ["scripts/am_patch/gates.py"]
