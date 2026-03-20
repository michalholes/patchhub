from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_python_gate_runner_mode_uses_runner_interpreter(tmp_path: Path) -> None:
    from am_patch.python_gate_runtime import resolve_python_gate_interpreter

    result = resolve_python_gate_interpreter(
        active_repository_tree_root=tmp_path,
        python_gate_mode="runner",
        python_gate_python=".venv/bin/python",
    )

    assert result == sys.executable


def test_python_gate_auto_prefers_repo_local_interpreter(tmp_path: Path) -> None:
    from am_patch.python_gate_runtime import resolve_python_gate_interpreter

    repo_python = tmp_path / ".venv" / "bin" / "python"
    repo_python.parent.mkdir(parents=True)
    repo_python.write_text("", encoding="utf-8")

    result = resolve_python_gate_interpreter(
        active_repository_tree_root=tmp_path,
        python_gate_mode="auto",
        python_gate_python=".venv/bin/python",
    )

    assert result == str(repo_python.resolve())


def test_python_gate_required_missing_is_config_invalid(tmp_path: Path) -> None:
    from am_patch.errors import RunnerError
    from am_patch.python_gate_runtime import resolve_python_gate_interpreter

    with pytest.raises(RunnerError) as excinfo:
        resolve_python_gate_interpreter(
            active_repository_tree_root=tmp_path,
            python_gate_mode="required",
            python_gate_python=".venv/bin/python",
        )

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"


def test_python_gate_relpath_escape_is_config_invalid(tmp_path: Path) -> None:
    from am_patch.errors import RunnerError
    from am_patch.python_gate_runtime import resolve_python_gate_interpreter

    with pytest.raises(RunnerError) as excinfo:
        resolve_python_gate_interpreter(
            active_repository_tree_root=tmp_path,
            python_gate_mode="auto",
            python_gate_python="../venv/bin/python",
        )

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"
