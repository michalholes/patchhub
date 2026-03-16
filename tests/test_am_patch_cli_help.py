from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _runner_path(repo_root: Path) -> Path:
    return repo_root / "amp" / "am_patch.py"


def _configured_policy_bits(repo_root: Path) -> tuple[str, list[str]]:
    data = tomllib.loads((repo_root / "amp" / "am_patch.toml").read_text(encoding="utf-8"))
    flat: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                flat[str(subkey)] = subvalue
        else:
            flat[str(key)] = value
    mode = str(flat.get("pytest_routing_mode", "bucketed"))
    raw = flat.get("gate_pytest_py_prefixes", ["amp", "tests"])
    prefixes = [str(item) for item in raw] if isinstance(raw, list) else []
    return mode, prefixes


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = _repo_root()
    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"
    return subprocess.run(
        [sys.executable, str(_runner_path(repo_root)), *args],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )


def test_am_patch_help_smoke() -> None:
    repo_root = _repo_root()
    assert _runner_path(repo_root).exists()
    proc = _run("--help")
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert out.strip()


def test_am_patch_help_all_mentions_pytest_routing_mode() -> None:
    proc = _run("--help-all")
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "--pytest-routing-mode legacy|bucketed" in out


def test_am_patch_show_config_prints_pytest_routing_keys() -> None:
    repo_root = _repo_root()
    expected_mode, expected_prefixes = _configured_policy_bits(repo_root)
    proc = _run("--show-config")
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert f"pytest_routing_mode={expected_mode!r}" in out
    assert f"gate_pytest_py_prefixes={expected_prefixes!r}" in out
    assert "pytest_roots=" in out
    assert "pytest_namespace_modules=" in out
    assert "pytest_dependencies=" in out
    assert "pytest_external_dependencies=" in out


def test_am_patch_help_all_mentions_root_layout_contract() -> None:
    proc = _run("--help-all")
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "Relative paths are resolved against runner_root." in out
    assert "Embedded default: amp/am_patch.toml" in out
    assert "Root-layout default: am_patch.toml in runner_root" in out
    assert "Relative paths are resolved against repo root." not in out
