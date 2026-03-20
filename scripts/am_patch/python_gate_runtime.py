from __future__ import annotations

import os
import sys
from pathlib import Path

from am_patch.errors import RunnerError


def _infer_venv_root_from_python(python_exe: str) -> Path | None:
    path = Path(python_exe)
    if path.name == "python" and path.parent.name == "bin" and path.parent.parent.name == ".venv":
        return path.parent.parent
    return None


def resolve_python_gate_interpreter(
    *,
    active_repository_tree_root: Path,
    python_gate_mode: str,
    python_gate_python: str,
) -> str:
    mode = str(python_gate_mode or "auto").strip()
    if mode not in {"runner", "auto", "required"}:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "python_gate_mode must be runner|auto|required",
        )

    if mode == "runner":
        return sys.executable

    relpath = str(python_gate_python or "").strip()
    if not relpath:
        raise RunnerError("CONFIG", "INVALID", "python_gate_python must be non-empty")

    repo_root = active_repository_tree_root.resolve()
    repo_python = (repo_root / relpath).resolve()
    try:
        repo_python.relative_to(repo_root)
    except ValueError as exc:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "python_gate_python escapes the active repository tree root",
        ) from exc

    if repo_python.exists():
        return str(repo_python)
    if mode == "required":
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"required repo-local python gate interpreter not found: {repo_python}",
        )
    return sys.executable


def build_python_gate_env(*, python_exe: str) -> dict[str, str]:
    env = dict(os.environ)
    venv_root = _infer_venv_root_from_python(python_exe)
    if venv_root is None:
        return env
    venv_bin = venv_root / "bin"
    old_path = env.get("PATH", "")
    env["PATH"] = f"{venv_bin}:{old_path}" if old_path else str(venv_bin)
    env["VIRTUAL_ENV"] = str(venv_root)
    return env
