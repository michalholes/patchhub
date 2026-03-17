from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _configured_pytest_py_prefixes(repo_root: Path) -> list[str]:
    config_path = repo_root / "scripts" / "am_patch" / "am_patch.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    flat: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                flat[str(subkey)] = subvalue
        else:
            flat[str(key)] = value
    raw = flat.get("gate_pytest_py_prefixes", ["tests", "src", "plugins", "scripts"])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _configured_pytest_routing_mode(repo_root: Path) -> str:
    config_path = repo_root / "scripts" / "am_patch" / "am_patch.toml"
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    flat: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                flat[str(subkey)] = subvalue
        else:
            flat[str(key)] = value
    return str(flat.get("pytest_routing_mode", "bucketed"))


@pytest.mark.parametrize(
    "rel_script, extra_env",
    [
        ("scripts/am_patch.py", {"AM_PATCH_VENV_BOOTSTRAPPED": "1"}),
        ("scripts/check_patch_pm.py", {}),
        ("scripts/gov_versions.py", {}),
        ("scripts/sync_issues_archive.py", {}),
    ],
)
def test_scripts_help_smoke(rel_script: str, extra_env: dict[str, str]) -> None:
    repo_root = _repo_root()
    script_path = repo_root / rel_script
    assert script_path.exists(), f"missing script: {rel_script}"

    env = os.environ.copy()
    env.update(extra_env)

    p = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, f"help failed for {rel_script}: rc={p.returncode}\n{out}"
    assert out.strip(), f"no help output for {rel_script}"


def test_am_patch_help_all_mentions_pytest_routing_mode() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [sys.executable, str(script_path), "--help-all"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out
    assert "--pytest-routing-mode legacy|bucketed" in out


def test_am_patch_show_config_prints_pytest_routing_keys() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [sys.executable, str(script_path), "--show-config"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out

    expected_mode = _configured_pytest_routing_mode(repo_root)
    expected_py_prefixes = _configured_pytest_py_prefixes(repo_root)
    assert f"pytest_routing_mode={expected_mode!r}" in out
    assert f"gate_pytest_py_prefixes={expected_py_prefixes!r}" in out
    assert "pytest_roots=" in out
    assert "pytest_namespace_modules=" in out
    assert "pytest_dependencies=" in out
    assert "pytest_external_dependencies=" in out


def test_am_patch_help_all_mentions_dual_layout_config_contract() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [sys.executable, str(script_path), "--help-all"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out
    assert "Relative paths are resolved against runner_root." in out
    assert "Embedded default: scripts/am_patch/am_patch.toml" in out
    assert "Root-layout default: am_patch.toml in runner_root" in out
    assert "Relative paths are resolved against repo root." not in out


def test_am_patch_help_all_mentions_target_cli_surface() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [sys.executable, str(script_path), "--help-all"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out
    assert "--target-repo-name NAME" in out
    assert "--active-target-repo-root PATH" in out
    assert "--target-repo-roots CSV" in out


def test_am_patch_show_config_prints_target_repo_name_default_and_cli_override() -> (
    None
):
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p_default = subprocess.run(
        [sys.executable, str(script_path), "--show-config"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out_default = (p_default.stdout or "") + (p_default.stderr or "")
    assert p_default.returncode == 0, out_default
    assert "target_repo_name='audiomason2' (src=config)" in out_default

    p_cli = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--show-config",
            "--target-repo-name",
            "patchhub",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out_cli = (p_cli.stdout or "") + (p_cli.stderr or "")
    assert p_cli.returncode == 0, out_cli
    assert "target_repo_name='patchhub' (src=cli)" in out_cli


def test_am_patch_show_config_prints_target_root_cli_overrides() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--show-config",
            "--target-repo-roots",
            "/tmp/target_a,/tmp/target_b",
            "--active-target-repo-root",
            "/tmp/target_b",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out
    assert "target_repo_roots=['/tmp/target_a', '/tmp/target_b'] (src=cli)" in out
    assert "active_target_repo_root='/tmp/target_b' (src=cli)" in out


def test_am_patch_show_config_target_cli_last_occurrence_and_csv_replace() -> None:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "am_patch.py"

    env = os.environ.copy()
    env["AM_PATCH_VENV_BOOTSTRAPPED"] = "1"

    p = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--show-config",
            "--target-repo-name",
            "audiomason2",
            "--override",
            "target_repo_name=patchhub",
            "--override",
            "target_repo_roots=/tmp/one",
            "--target-repo-roots",
            "/tmp/two,/tmp/three",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out
    assert "target_repo_name='patchhub' (src=cli)" in out
    assert "target_repo_roots=['/tmp/two', '/tmp/three'] (src=cli)" in out
