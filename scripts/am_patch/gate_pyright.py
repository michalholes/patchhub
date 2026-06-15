from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .python_gate_runtime import build_python_gate_env, resolve_python_gate_interpreter

if TYPE_CHECKING:
    from .log import Logger


def _norm_rel_path(p: str) -> str:
    s = str(p).strip().replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _norm_targets(targets: list[str]) -> list[str]:
    out: list[str] = []
    for target in targets:
        prefix = _norm_rel_path(target)
        if prefix and prefix not in out:
            out.append(prefix)
    return out


def should_run_pyright(*, decision_paths: list[str], targets: list[str]) -> bool:
    prefixes = _norm_targets(targets)
    if not prefixes:
        return False
    for relpath in decision_paths:
        norm = _norm_rel_path(relpath)
        if norm == "pyrightconfig.json":
            return True
        if not norm.endswith(".py"):
            continue
        for prefix in prefixes:
            if norm == prefix or norm.startswith(prefix + "/"):
                return True
    return False


def run_pyright(
    logger: Logger,
    cwd: Path,
    *,
    active_repository_tree_root: Path,
    python_gate_mode: str,
    python_gate_python: str,
) -> bool:
    py = resolve_python_gate_interpreter(
        active_repository_tree_root=active_repository_tree_root,
        python_gate_mode=python_gate_mode,
        python_gate_python=python_gate_python,
    )
    logger.section("GATE: PYRIGHT")
    logger.line(f"pyright_python={py}")
    env = build_python_gate_env(python_exe=py)
    r = logger.run_logged(["pyright"], cwd=cwd, env=env)
    return r.returncode == 0
