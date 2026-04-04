from __future__ import annotations

# Canonical workflow-effective traversal authority for governance tooling.
from typing import TypedDict


class WorkflowEffectiveContextError(Exception):
    pass


class WorkflowEffectiveContext(TypedDict):
    effective_step_ids: list[str]
    effective_capabilities: list[str]
    effective_rule_ids: list[str]
    effective_full_rule_text: dict[str, str]


def _object_map(objects: list[dict], kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for obj in objects:
        if obj.get("type") != kind:
            continue
        obj_id = str(obj.get("id", "")).strip()
        if obj_id:
            out[obj_id] = obj
    return out


def _id_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for item in values:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def build_workflow_effective_context(
    objects: list[dict],
    entry_step_id: str,
) -> WorkflowEffectiveContext:
    steps = _object_map(objects, "workflow_step")
    capabilities = _object_map(objects, "capability")
    rules = _object_map(objects, "rule")
    if entry_step_id not in steps:
        raise WorkflowEffectiveContextError(f"missing_workflow_step:{entry_step_id}")

    effective_step_ids: list[str] = []
    seen_steps: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in seen_steps:
            return
        step = steps.get(step_id)
        if step is None:
            raise WorkflowEffectiveContextError(f"missing_workflow_step:{step_id}")
        seen_steps.add(step_id)
        effective_step_ids.append(step_id)
        for child_id in _id_list(step.get("required_substeps", [])):
            visit(child_id)

    visit(entry_step_id)

    effective_capabilities: list[str] = []
    seen_capabilities: set[str] = set()
    for step_id in effective_step_ids:
        step = steps[step_id]
        for capability_id in _id_list(step.get("required_capabilities", [])):
            if capability_id in seen_capabilities:
                continue
            if capability_id not in capabilities:
                raise WorkflowEffectiveContextError(f"missing_capability:{capability_id}")
            seen_capabilities.add(capability_id)
            effective_capabilities.append(capability_id)

    effective_rule_ids: list[str] = []
    effective_full_rule_text: dict[str, str] = {}
    seen_rules: set[str] = set()
    for capability_id in effective_capabilities:
        capability = capabilities[capability_id]
        for rule_id in _id_list(capability.get("triggers_rules", [])):
            rule = rules.get(rule_id)
            if rule is None:
                raise WorkflowEffectiveContextError(f"missing_rule:{rule_id}")
            if rule_id in seen_rules:
                continue
            seen_rules.add(rule_id)
            effective_rule_ids.append(rule_id)
            effective_full_rule_text[rule_id] = str(rule.get("statement", ""))

    return {
        "effective_step_ids": effective_step_ids,
        "effective_capabilities": effective_capabilities,
        "effective_rule_ids": effective_rule_ids,
        "effective_full_rule_text": effective_full_rule_text,
    }


__all__ = [
    "WorkflowEffectiveContext",
    "WorkflowEffectiveContextError",
    "_id_list",
    "_object_map",
    "build_workflow_effective_context",
]
