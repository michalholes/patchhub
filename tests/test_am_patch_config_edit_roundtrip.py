from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import tomllib


def test_config_edit_roundtrip_preserves_comments_and_builds_policy() -> None:
    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_bootstrap_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    original = cfg_path.read_text(encoding="utf-8")
    schema = get_bootstrap_policy_schema()

    updated = apply_update_to_config_text(
        original,
        {
            "ipc_socket_enabled": False,
            "verbosity": "quiet",
            "success_archive_name": "{repo}-{branch}.zip",
            "target_repo_name": "patchhub",
        },
        schema,
    )

    assert "# debug | verbose | normal | quiet" in updated
    assert 'verbosity = "quiet"' in updated
    assert "ipc_socket_enabled = false" in updated
    assert 'success_archive_name = "{repo}-{branch}.zip"' in updated
    assert 'target_repo_name = "patchhub"' in updated


def test_config_edit_roundtrip_handles_bootstrap_root_model_keys() -> None:
    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_bootstrap_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    schema = get_bootstrap_policy_schema()

    updated = apply_update_to_config_text(
        cfg_path.read_text(encoding="utf-8"),
        {
            "artifacts_root": "/tmp/am_patch_artifacts",
            "target_repo_roots": ["/tmp/target_a", "/tmp/target_b"],
            "active_target_repo_root": "/tmp/target_b",
            "target_repo_config_relpath": ".am_patch/custom.repo.toml",
        },
        schema,
    )

    assert 'artifacts_root = "/tmp/am_patch_artifacts"' in updated
    assert 'target_repo_roots = ["/tmp/target_a", "/tmp/target_b"]' in updated
    assert 'active_target_repo_root = "/tmp/target_b"' in updated
    assert 'target_repo_config_relpath = ".am_patch/custom.repo.toml"' in updated

    data = tomllib.loads(updated)
    paths = data["paths"]
    top_level_keys = {k for k, v in data.items() if not isinstance(v, dict)}

    assert paths["artifacts_root"] == "/tmp/am_patch_artifacts"
    assert paths["target_repo_roots"] == ["/tmp/target_a", "/tmp/target_b"]
    assert paths["active_target_repo_root"] == "/tmp/target_b"
    assert paths["target_repo_config_relpath"] == ".am_patch/custom.repo.toml"
    assert "artifacts_root" not in top_level_keys
    assert "target_repo_roots" not in top_level_keys
    assert "active_target_repo_root" not in top_level_keys
    assert "target_repo_config_relpath" not in top_level_keys


def test_shipped_config_uses_bootstrap_only_target_selection_examples() -> None:
    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    original = cfg_path.read_text(encoding="utf-8")

    assert 'target_repo_roots = ["patchhub=."]' in original
    assert 'target_repo_config_relpath = ".am_patch/am_patch.repo.toml"' in original
    assert '# active_target_repo_root = "."' in original
    assert '# patch_dir = "patches"' in original
    assert "/home/pi/audiomason2" not in original
    assert "/home/pi/patchhub" not in original


def test_config_edit_roundtrip_keeps_target_selection_comments() -> None:
    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_bootstrap_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    schema = get_bootstrap_policy_schema()

    updated = apply_update_to_config_text(
        cfg_path.read_text(encoding="utf-8"),
        {
            "target_repo_name": "patchhub",
            "target_repo_roots": [
                "audiomason2=/srv/targets/audiomason2",
                "patchhub=/srv/targets/patchhub",
            ],
            "active_target_repo_root": "/srv/targets/patchhub",
        },
        schema,
    )

    assert "token=root bindings" in updated
    assert (
        'target_repo_roots = ["audiomason2=/srv/targets/audiomason2", '
        '"patchhub=/srv/targets/patchhub"]'
    ) in updated
    assert 'active_target_repo_root = "/srv/targets/patchhub"' in updated
