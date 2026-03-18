from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import tomllib


def test_config_edit_roundtrip_preserves_comments_and_builds_policy():
    from pathlib import Path

    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    original = cfg_path.read_text(encoding="utf-8")
    schema = get_policy_schema()

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


def test_config_edit_roundtrip_handles_bucketed_pytest_routing_keys() -> None:
    from pathlib import Path

    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    schema = get_policy_schema()

    updated = apply_update_to_config_text(
        cfg_path.read_text(encoding="utf-8"),
        {
            "gate_pytest_py_prefixes": ["badguys", "scripts/am_patch"],
            "pytest_routing_mode": "legacy",
            "pytest_roots": {"amp.*": "scripts/am_patch/"},
            "pytest_namespace_modules": {"amp": ["am_patch", "scripts.am_patch"]},
            "pytest_dependencies": {"amp.phb": ["amp"]},
            "pytest_external_dependencies": {"amp.phb": ["amp.badguys"]},
        },
        schema,
    )

    assert 'gate_pytest_py_prefixes = ["badguys", "scripts/am_patch"]' in updated
    assert 'pytest_routing_mode = "legacy"' in updated
    assert "[pytest_roots]" in updated
    assert '"amp.*" = "scripts/am_patch/"' in updated
    assert "[pytest_namespace_modules]" in updated
    assert '"amp" = ["am_patch", "scripts.am_patch"]' in updated
    assert "[pytest_dependencies]" in updated
    assert '"amp.phb" = ["amp"]' in updated
    assert "[pytest_external_dependencies]" in updated
    assert '"amp.phb" = ["amp.badguys"]' in updated


def test_config_edit_roundtrip_handles_root_model_keys() -> None:
    from pathlib import Path

    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    schema = get_policy_schema()

    updated = apply_update_to_config_text(
        cfg_path.read_text(encoding="utf-8"),
        {
            "artifacts_root": "/tmp/am_patch_artifacts",
            "target_repo_roots": ["/tmp/target_a", "/tmp/target_b"],
            "active_target_repo_root": "/tmp/target_b",
        },
        schema,
    )

    assert 'artifacts_root = "/tmp/am_patch_artifacts"' in updated
    assert 'target_repo_roots = ["/tmp/target_a", "/tmp/target_b"]' in updated
    assert 'active_target_repo_root = "/tmp/target_b"' in updated

    data = tomllib.loads(updated)
    paths = data["paths"]
    top_level_keys = {k for k, v in data.items() if not isinstance(v, dict)}

    assert paths["artifacts_root"] == "/tmp/am_patch_artifacts"
    assert paths["target_repo_roots"] == ["/tmp/target_a", "/tmp/target_b"]
    assert paths["active_target_repo_root"] == "/tmp/target_b"
    assert "artifacts_root" not in top_level_keys
    assert "target_repo_roots" not in top_level_keys
    assert "active_target_repo_root" not in top_level_keys


def test_config_edit_roundtrip_keeps_target_selection_comments() -> None:
    from pathlib import Path

    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_policy_schema

    cfg_path = Path(__file__).parent.parent / "scripts" / "am_patch" / "am_patch.toml"
    schema = get_policy_schema()

    updated = apply_update_to_config_text(
        cfg_path.read_text(encoding="utf-8"),
        {
            "target_repo_name": "patchhub",
            "target_repo_roots": ["/home/pi/audiomason2", "/home/pi/patchhub"],
            "active_target_repo_root": "/home/pi/patchhub",
        },
        schema,
    )

    assert "/home/pi/<name>" in updated
    assert 'target_repo_roots = ["/home/pi/audiomason2", "/home/pi/patchhub"]' in updated
    assert 'active_target_repo_root = "/home/pi/patchhub"' in updated
