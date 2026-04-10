# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from patchhub.app_api_amp import api_amp_config_post, api_amp_schema
from patchhub.fs_jail import FsJail


class _Dummy:
    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.cfg = SimpleNamespace(
            runner=SimpleNamespace(runner_config_toml="scripts/am_patch/am_patch.toml")
        )
        self.jail = FsJail(
            repo_root=repo_root,
            patches_root_rel="patches",
            crud_allowlist=[""],
            allow_crud=True,
        )


def test_amp_bootstrap_surface_excludes_repo_owned_keys() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "patches").mkdir(parents=True)
        (root / "scripts" / "am_patch").mkdir(parents=True)
        (root / "scripts" / "am_patch" / "am_patch.toml").write_text(
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("scripts", "am_patch", "am_patch.toml")
            .read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        dummy = _Dummy(repo_root=root)

        status, data = api_amp_schema(dummy)
        assert status == 200
        obj = json.loads(data.decode("utf-8"))
        policy = obj["schema"]["policy"]

        assert "target_repo_config_relpath" in policy
        assert "artifacts_root" in policy
        assert "self_backup_mode" in policy
        assert "patch_script_archive_enabled" in policy
        assert "artifact_stage_enabled" in policy
        assert "self_backup_dir" in policy
        assert "self_backup_template" in policy
        assert "self_backup_include_relpaths" in policy
        assert "default_branch" not in policy
        assert "python_gate_mode" not in policy
        assert "gate_monolith_enabled" not in policy


def test_amp_bootstrap_roundtrip_does_not_write_repo_owned_keys() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "patches").mkdir(parents=True)
        (root / "scripts" / "am_patch").mkdir(parents=True)
        cfg_path = root / "scripts" / "am_patch" / "am_patch.toml"
        cfg_path.write_text(
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("scripts", "am_patch", "am_patch.toml")
            .read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        dummy = _Dummy(repo_root=root)

        status, data = api_amp_config_post(
            dummy,
            {
                "values": {
                    "verbosity": "quiet",
                    "target_repo_config_relpath": ".am_patch/custom.repo.toml",
                    "artifacts_root": "../artifacts-root",
                    "self_backup_mode": "never",
                    "patch_script_archive_enabled": False,
                    "artifact_stage_enabled": False,
                    "self_backup_dir": "safe/quarantine",
                    "self_backup_template": "custom_issue{issue}_{ts}.zip",
                    "self_backup_include_relpaths": [
                        "scripts/custom.py",
                        "scripts/custom/",
                    ],
                },
                "dry_run": False,
            },
        )
        assert status == 200, data.decode("utf-8")

        saved = cfg_path.read_text(encoding="utf-8")
        assert 'verbosity = "quiet"' in saved
        assert 'target_repo_config_relpath = ".am_patch/custom.repo.toml"' in saved
        assert 'self_backup_dir = "safe/quarantine"' in saved
        assert "patch_script_archive_enabled = false" in saved
        assert "artifact_stage_enabled = false" in saved
        assert "default_branch =" not in saved
        assert "python_gate_mode =" not in saved
