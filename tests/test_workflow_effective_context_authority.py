from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_governance_modules() -> tuple[object, object, object]:
    return (
        importlib.import_module("governance.gov_navigator"),
        importlib.import_module("governance.rc_resolver"),
        importlib.import_module("governance.workflow_effective_context"),
    )


def test_workflow_effective_context_exports_authority_api() -> None:
    _gov_navigator, _rc_resolver, workflow_effective_context = _load_governance_modules()

    assert workflow_effective_context.__all__ == [
        "WorkflowEffectiveContext",
        "WorkflowEffectiveContextError",
        "_id_list",
        "_object_map",
        "build_workflow_effective_context",
    ]
    assert callable(workflow_effective_context.build_workflow_effective_context)


def test_rc_resolver_reuses_canonical_workflow_effective_context() -> None:
    _gov_navigator, rc_resolver, workflow_effective_context = _load_governance_modules()

    assert rc_resolver.build_workflow_effective_context is (
        workflow_effective_context.build_workflow_effective_context
    )


def test_gov_navigator_reuses_canonical_workflow_effective_context() -> None:
    gov_navigator, _rc_resolver, workflow_effective_context = _load_governance_modules()

    assert gov_navigator.build_workflow_effective_context is (
        workflow_effective_context.build_workflow_effective_context
    )


def test_pm_validator_pack_contract_imports_canonical_workflow_module() -> None:
    text = (REPO_ROOT / "governance" / "pm_validator_pack_contract.py").read_text(encoding="utf-8")
    assert "from .workflow_effective_context import (" in text
    assert "from workflow_effective_context import (" in text
    assert "from .rc_resolver import (" not in text
    assert "from rc_resolver import (" not in text


def test_build_workflow_effective_context_returns_authority_ordered_payload() -> None:
    _gov_navigator, _rc_resolver, workflow_effective_context = _load_governance_modules()

    objects = [
        {
            "type": "workflow_step",
            "id": "entry",
            "required_substeps": ["child"],
            "required_capabilities": ["cap.entry", "cap.shared"],
        },
        {
            "type": "workflow_step",
            "id": "child",
            "required_capabilities": ["cap.child", "cap.shared"],
        },
        {
            "type": "capability",
            "id": "cap.entry",
            "triggers_rules": ["rule.entry", "rule.shared"],
        },
        {
            "type": "capability",
            "id": "cap.child",
            "triggers_rules": ["rule.child", "rule.shared"],
        },
        {
            "type": "capability",
            "id": "cap.shared",
            "triggers_rules": ["rule.shared"],
        },
        {"type": "rule", "id": "rule.entry", "statement": "Entry rule"},
        {"type": "rule", "id": "rule.child", "statement": "Child rule"},
        {"type": "rule", "id": "rule.shared", "statement": "Shared rule"},
    ]

    ctx = workflow_effective_context.build_workflow_effective_context(objects, "entry")

    assert ctx["effective_step_ids"] == ["entry", "child"]
    assert ctx["effective_capabilities"] == [
        "cap.entry",
        "cap.shared",
        "cap.child",
    ]
    assert ctx["effective_rule_ids"] == ["rule.entry", "rule.shared", "rule.child"]
    assert ctx["effective_full_rule_text"] == {
        "rule.entry": "Entry rule",
        "rule.shared": "Shared rule",
        "rule.child": "Child rule",
    }
