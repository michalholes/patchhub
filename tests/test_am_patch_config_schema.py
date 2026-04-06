from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_policy_schema_includes_all_policy_fields():
    from dataclasses import fields

    from am_patch.config import Policy
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    policy = schema.get("policy")
    assert isinstance(policy, dict)

    expected = {f.name for f in fields(Policy) if f.name != "_src"}
    assert set(policy.keys()) == expected


def test_policy_schema_exposes_bucketed_pytest_routing_keys() -> None:
    from am_patch.config_schema import SCHEMA_VERSION, get_policy_schema

    schema = get_policy_schema()
    policy = schema["policy"]

    assert SCHEMA_VERSION == "10"
    assert schema["schema_version"] == "10"
    assert policy["gate_pytest_py_prefixes"]["type"] == "list[str]"
    assert policy["pytest_routing_mode"]["enum"] == ["legacy", "bucketed"]
    assert policy["pytest_roots"]["type"] == "dict[str,str]"
    assert policy["pytest_namespace_modules"]["type"] == "dict[str,list[str]]"
    assert policy["pytest_dependencies"]["type"] == "dict[str,list[str]]"
    assert policy["pytest_external_dependencies"]["type"] == "dict[str,list[str]]"
    assert policy["failure_zip_enabled"]["type"] == "bool"
    assert policy["success_archive_enabled"]["type"] == "bool"
    assert policy["issue_diff_bundle_enabled"]["type"] == "bool"


def test_policy_schema_exposes_root_model_keys() -> None:
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    policy = schema["policy"]

    assert policy["repo_root"]["section"] == "paths"
    assert policy["artifacts_root"]["section"] == "paths"
    assert policy["target_repo_roots"]["section"] == "paths"
    assert policy["active_target_repo_root"]["section"] == "paths"
    assert policy["target_repo_config_relpath"]["section"] == "paths"
    assert policy["artifacts_root"]["type"] == "optional[str]"
    assert policy["target_repo_roots"]["type"] == "list[str]"
    assert policy["active_target_repo_root"]["type"] == "optional[str]"


def test_policy_schema_exposes_target_repo_name() -> None:
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    target = schema["policy"]["target_repo_name"]

    assert target["type"] == "str"
    assert target["section"] == ""
    assert target["default"] == ""
    assert "resolved through target_repo_roots" in target["help"]


def test_bootstrap_policy_schema_is_bootstrap_only() -> None:
    from am_patch.config import BOOTSTRAP_OWNED_KEYS
    from am_patch.config_schema import get_bootstrap_policy_schema

    schema = get_bootstrap_policy_schema()
    policy = schema["policy"]

    assert set(policy.keys()) == BOOTSTRAP_OWNED_KEYS
    assert "target_repo_config_relpath" in policy
    assert "failure_zip_enabled" in policy
    assert "success_archive_enabled" in policy
    assert "issue_diff_bundle_enabled" in policy
    assert "python_gate_mode" not in policy
    assert "default_branch" not in policy


def test_policy_schema_exposes_self_backup_keys() -> None:
    from am_patch.config_schema import get_policy_schema

    policy = get_policy_schema()["policy"]

    assert policy["self_backup_mode"]["type"] == "str"
    assert policy["self_backup_mode"]["enum"] == ["never", "initial_self_patch"]
    assert policy["self_backup_mode"]["default"] == "initial_self_patch"
    assert policy["self_backup_dir"]["type"] == "str"
    assert policy["self_backup_dir"]["default"] == "quarantine"
    assert policy["self_backup_template"]["type"] == "str"
    assert policy["self_backup_template"]["default"] == "amp_self_backup_issue{issue}_{ts}.zip"
    assert policy["self_backup_include_relpaths"]["type"] == "list[str]"
    assert policy["self_backup_include_relpaths"]["default"] == [
        "scripts/am_patch.py",
        "scripts/am_patch/",
    ]
