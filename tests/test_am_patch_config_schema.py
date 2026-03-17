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

    assert SCHEMA_VERSION == "6"
    assert schema["schema_version"] == "6"
    assert policy["gate_pytest_py_prefixes"]["type"] == "list[str]"
    assert policy["pytest_routing_mode"]["enum"] == ["legacy", "bucketed"]
    assert policy["pytest_roots"]["type"] == "dict[str,str]"
    assert policy["pytest_namespace_modules"]["type"] == "dict[str,list[str]]"
    assert policy["pytest_dependencies"]["type"] == "dict[str,list[str]]"
    assert policy["pytest_external_dependencies"]["type"] == "dict[str,list[str]]"


def test_policy_schema_exposes_root_model_keys() -> None:
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    policy = schema["policy"]

    assert policy["repo_root"]["section"] == "paths"
    assert policy["artifacts_root"]["section"] == "paths"
    assert policy["target_repo_roots"]["section"] == "paths"
    assert policy["active_target_repo_root"]["section"] == "paths"
    assert policy["artifacts_root"]["type"] == "optional[str]"
    assert policy["target_repo_roots"]["type"] == "list[str]"
    assert policy["active_target_repo_root"]["type"] == "optional[str]"


def test_policy_schema_exposes_target_repo_name() -> None:
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    target = schema["policy"]["target_repo_name"]

    assert target["type"] == "str"
    assert target["section"] == ""
    assert target["default"] == "audiomason2"
    assert "bare repo token selector" in target["help"]
