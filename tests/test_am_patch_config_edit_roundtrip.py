from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_config_edit_roundtrip_updates_self_backup_keys() -> None:
    from am_patch.config_edit import apply_update_to_config_text
    from am_patch.config_schema import get_bootstrap_policy_schema

    original_text = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("scripts", "am_patch", "am_patch.toml")
        .read_text(encoding="utf-8")
    )
    schema = get_bootstrap_policy_schema()

    updated = apply_update_to_config_text(
        original_text,
        {
            "artifacts_root": "../artifacts-root",
            "self_backup_mode": "never",
            "self_backup_dir": "safe/quarantine",
            "self_backup_template": "custom_issue{issue}_{ts}.zip",
            "self_backup_include_relpaths": ["scripts/custom.py", "scripts/custom/"],
        },
        schema,
    )

    assert 'artifacts_root = "../artifacts-root"' in updated
    assert 'self_backup_mode = "never"' in updated
    assert 'self_backup_dir = "safe/quarantine"' in updated
    assert 'self_backup_template = "custom_issue{issue}_{ts}.zip"' in updated
    assert 'self_backup_include_relpaths = ["scripts/custom.py", "scripts/custom/"]' in updated
