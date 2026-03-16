from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _amp_symbols():
    from am_patch.config import Policy
    from am_patch.config_file import resolve_config_path
    from am_patch.errors import RunnerError
    from am_patch.root_model import resolve_root_model
    from am_patch.startup_context import _detect_runner_root

    return Policy, resolve_config_path, RunnerError, resolve_root_model, _detect_runner_root


def test_resolve_config_path_uses_root_layout_default(tmp_path: Path) -> None:
    _, resolve_config_path, _, _, _ = _amp_symbols()
    runner_root = tmp_path / "runner"
    package_dir = runner_root / "am_patch"
    package_dir.mkdir(parents=True)
    cfg_path = runner_root / "am_patch.toml"
    cfg_path.write_text('verbosity = "normal"\n', encoding="utf-8")

    assert resolve_config_path(None, runner_root, runner_root) == cfg_path


def test_detect_runner_root_supports_root_layout(tmp_path: Path) -> None:
    _, _, _, _, detect_runner_root = _amp_symbols()
    runner_root = tmp_path / "runner"
    package_dir = runner_root / "am_patch"
    package_dir.mkdir(parents=True)
    module_path = package_dir / "startup_context.py"
    module_path.write_text("# stub\n", encoding="utf-8")

    assert detect_runner_root(module_path) == runner_root


def test_legacy_repo_root_without_registry_rejects_non_runner_target(tmp_path: Path) -> None:
    policy_cls, _, runner_error_cls, resolve_root_model, _ = _amp_symbols()
    runner_root = tmp_path / "runner"
    runner_root.mkdir()
    denied = tmp_path / "denied"
    denied.mkdir()
    policy = policy_cls(repo_root=str(denied))

    match = "repo_root must resolve to runner_root or an entry from target_repo_roots"
    with pytest.raises(runner_error_cls, match=match):
        resolve_root_model(policy, runner_root=runner_root)


def test_build_effective_policy_uses_root_layout_default_config(tmp_path: Path) -> None:
    runner_root = tmp_path / "runner"
    package_dir = runner_root / "am_patch"
    shutil.copytree(Path("amp/am_patch"), package_dir)
    shutil.copy2(Path("amp/am_patch.py"), runner_root / "am_patch.py")
    (runner_root / "am_patch.toml").write_text('verbosity = "quiet"\n', encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from am_patch.engine import build_effective_policy; "
                "res = build_effective_policy(['173', 'msg', 'patch.patch']); "
                "print(res[2])"
            ),
        ],
        cwd=str(runner_root),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert proc.stdout.strip() == str((runner_root / "am_patch.toml").resolve())


def test_shipped_toml_surfaces_root_model_keys() -> None:
    text = Path("amp/am_patch.toml").read_text(encoding="utf-8")
    assert 'target_repo_roots = [".."]' in text
    assert 'artifacts_root = ".."' in text
    assert 'active_target_repo_root = ".."' in text
