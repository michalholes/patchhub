from __future__ import annotations

import json
from typing import Any

_KIND_LABELS = {
    "meta": "Document metadata",
    "binding_meta": "Binding metadata",
    "obligation_binding": "Binding rule",
    "oracle": "Oracle",
    "rule": "Rule",
    "capability": "Capability",
    "provider": "Provider",
    "route": "Route",
    "surface": "Entry surface",
    "implementation": "Implementation",
    "workflow_step": "Workflow step",
    "workflow_transition": "Workflow transition",
    "workflow_gate": "Workflow gate",
    "workflow_invalidation": "Workflow invalidation",
    "workflow_rollback": "Workflow rollback",
    "section": "Section",
    "note": "Note",
    "source_meta": "Source metadata",
}

_PRIORITY = {"surface": 0, "route": 1, "workflow_step": 2, "capability": 3}
_REFERENCE_FIELDS: dict[str, list[tuple[str, str]]] = {
    "capability": [("triggers_rules", "rule")],
    "provider": [("provides_capabilities", "capability")],
    "route": [("covers_capabilities", "capability"), ("provider_chain", "provider")],
    "surface": [("route_ref", "route"), ("requires_capabilities", "capability")],
    "implementation": [("implements_route", "route"), ("declared_capabilities", "capability")],
    "obligation_binding": [("oracle_ref", "oracle")],
    "workflow_step": [
        ("surface_ref", "surface"),
        ("route_ref", "route"),
        ("required_capabilities", "capability"),
        ("required_substeps", "workflow_step"),
    ],
    "workflow_transition": [("from_step", "workflow_step"), ("to_step", "workflow_step")],
    "workflow_gate": [
        ("step_ref", "workflow_step"),
        ("gate_capabilities", "capability"),
        ("gate_rule_ids", "rule"),
    ],
    "workflow_invalidation": [
        ("failing_step", "workflow_step"),
        ("invalidates_step", "workflow_step"),
    ],
    "workflow_rollback": [
        ("from_step", "workflow_step"),
        ("rollback_to_step", "workflow_step"),
    ],
}

_TASKS = [
    ("fix_problem", "Fix a problem", "Start from the current validation issue."),
    ("add_safely", "Add something new", "Append a scaffold and validate before saving."),
    ("rename_relink", "Rename or relink", "Preview relation-aware changes before applying them."),
    ("check_impact", "Check impact", "Review the consequence before confirming the change."),
]

_SUMMARIES = {
    "surface": "This entry surface controls how users reach the editor.",
    "route": "This route controls capability coverage and provider wiring.",
    "capability": "This capability links rules, routes, providers, and workflow.",
    "provider": "This provider supplies capabilities used by one or more routes.",
    "implementation": "This implementation promises to satisfy its route.",
    "workflow_step": "This workflow step controls entry, transition, invalidation, and rollback.",
    "obligation_binding": "This binding rule tells downstream tooling which contract applies.",
    "rule": "This rule belongs to the authority corpus and can be triggered by capabilities.",
    "oracle": "This oracle anchors binding rules to a named source of truth.",
    "meta": "This metadata block defines corpus counts and structural versioning.",
}


def _sid(obj: dict[str, Any]) -> str:
    return str(obj.get("id", "")).strip()


def _kind(obj: dict[str, Any]) -> str:
    return str(obj.get("type", "")).strip()


def _label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind.replace("_", " ").title())


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _title(obj: dict[str, Any]) -> str:
    for key in ("display_name", "name", "title"):
        value = str(obj.get(key, "")).strip()
        if value:
            return value
    if _kind(obj) == "rule":
        statement = str(obj.get("statement", "")).strip()
        if statement:
            return statement[:100]
    return _sid(obj) or _label(_kind(obj))


def _subtitle(obj: dict[str, Any]) -> str:
    kind = _kind(obj)
    if kind == "surface":
        route_ref = str(obj.get("route_ref", "")).strip()
        return f"Opens route {route_ref}" if route_ref else "Surface link missing"
    if kind == "route":
        return "Covers " + _stringify(obj.get("covers_capabilities", []))
    if kind == "workflow_step":
        branch = str(obj.get("branch", "")).strip()
        return f"Workflow branch {branch}" if branch else "Workflow step"
    if kind == "obligation_binding":
        role = str(obj.get("symbol_role", "")).strip()
        return f"Binding role {role}" if role else "Authority binding"
    return _label(kind)


def _local_fields(obj: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for key, value in obj.items():
        if key in {"type", "id"}:
            continue
        out.append({"label": key.replace("_", " "), "value": _stringify(value)})
    return out[:10]


def _index(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_sid(obj): obj for obj in objects if _sid(obj)}


def _expand(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else ([raw] if raw not in (None, "") else [])
    return [str(value).strip() for value in values if str(value).strip()]


def _outbound(selected: dict[str, Any], objects: list[dict[str, Any]]) -> list[dict[str, str]]:
    target_map = _index(objects)
    out: list[dict[str, str]] = []
    for field, relation_kind in _REFERENCE_FIELDS.get(_kind(selected), []):
        for target_id in _expand(selected.get(field)):
            target = target_map.get(target_id)
            out.append(
                {
                    "title": field.replace("_", " "),
                    "target_id": target_id,
                    "target_title": _title(target or {"id": target_id, "type": relation_kind}),
                    "kind": _label(relation_kind),
                }
            )
    return out


def _inbound(selected_id: str, objects: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for obj in objects:
        for field, _relation_kind in _REFERENCE_FIELDS.get(_kind(obj), []):
            for value in _expand(obj.get(field)):
                if value != selected_id:
                    continue
                out.append(
                    {
                        "title": field.replace("_", " "),
                        "target_id": _sid(obj),
                        "target_title": _title(obj),
                        "kind": _label(_kind(obj)),
                    }
                )
    return out


def _relation_sections(
    selected: dict[str, Any],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outbound = _outbound(selected, objects)
    inbound = _inbound(_sid(selected), objects)
    groups = {
        "What this points to": outbound,
        "What points back here": inbound,
        "What this requires": [
            item
            for item in outbound
            if item["title"]
            in {
                "requires capabilities",
                "required capabilities",
                "required substeps",
            }
        ],
        "What this covers or supplies": [
            item
            for item in outbound
            if item["title"]
            in {
                "covers capabilities",
                "provides capabilities",
                "provider chain",
                "declared capabilities",
            }
        ],
        "Process and workflow links": [
            item
            for item in outbound
            if item["title"]
            in {
                "from step",
                "to step",
                "step ref",
                "failing step",
                "invalidates step",
                "rollback to step",
            }
        ],
    }
    return [{"title": title, "items": items[:8]} for title, items in groups.items() if items]


def _manual_actions(selected: dict[str, Any]) -> list[dict[str, str]]:
    kind = _kind(selected)
    actions = [
        {"action_id": "rename_current_id", "label": "Rename selected id"},
        {"action_id": "delete_unsaved_block", "label": "Delete selected block"},
    ]
    if kind in {"surface", "implementation", "workflow_step"}:
        actions.append(
            {
                "action_id": "select_existing_route_ref",
                "label": "Relink to an existing route",
            }
        )
    if kind == "surface":
        actions.append(
            {
                "action_id": "select_existing_capabilities",
                "label": "Align required abilities",
            }
        )
    if kind == "obligation_binding":
        actions.append(
            {
                "action_id": "select_existing_oracle_ref",
                "label": "Relink to an existing oracle",
            }
        )
    return actions


def _preferred_selected_id(
    objects: list[dict[str, Any]],
    failure: dict[str, Any] | None,
    selected_id: str | None,
) -> str:
    wanted = str(selected_id or "").strip()
    ids = {_sid(obj) for obj in objects}
    if wanted and wanted in ids:
        return wanted
    if failure:
        for key in ("primary_id", "secondary_id"):
            candidate = str(failure.get(key, "")).strip()
            if candidate in ids:
                return candidate
    for preferred in ("surface", "route", "workflow_step", "capability"):
        for obj in objects:
            if _kind(obj) == preferred:
                return _sid(obj)
    return _sid(objects[0]) if objects else ""


def _navigation_items(
    objects: list[dict[str, Any]],
    failure: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    flagged = {
        str((failure or {}).get("primary_id", "")).strip(),
        str((failure or {}).get("secondary_id", "")).strip(),
    }
    items = []
    for obj in objects:
        obj_id = _sid(obj)
        items.append(
            {
                "id": obj_id,
                "title": _title(obj),
                "subtitle": _subtitle(obj),
                "kind": _kind(obj),
                "kind_label": _label(_kind(obj)),
                "has_failure": obj_id in flagged and bool(obj_id),
                "has_inbound": bool(_inbound(obj_id, objects)),
                "has_outbound": bool(_outbound(obj, objects)),
                "workflow_role": _kind(obj).startswith("workflow_"),
                "search_text": " ".join([obj_id, _kind(obj), _title(obj), _subtitle(obj)]).lower(),
            }
        )

    def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        kind = str(item.get("kind", ""))
        title = str(item.get("title", "")).lower()
        obj_id = str(item.get("id", ""))
        return (_PRIORITY.get(kind, 9), title, obj_id)

    items.sort(key=sort_key)
    return items


def _health(validated: bool, failure: dict[str, Any] | None, object_count: int) -> dict[str, Any]:
    if failure:
        return {
            "status": "problem",
            "headline": failure.get("title") or "Validation needs attention",
            "summary": "Repair the current validation problem before saving.",
            "recommended": (failure.get("actions") or [None])[0],
            "technical_reason": str(failure.get("failure_code", "")).strip(),
            "object_count": object_count,
        }
    if validated:
        return {
            "status": "healthy",
            "headline": "The document is currently healthy",
            "summary": "No validation issue is currently active for this workspace state.",
            "recommended": None,
            "technical_reason": "",
            "object_count": object_count,
        }
    return {
        "status": "unknown",
        "headline": "Validation has not been run on the current edits",
        "summary": (
            "Run Validate to confirm that the current workspace state is still safe to save."
        ),
        "recommended": None,
        "technical_reason": "",
        "object_count": object_count,
    }


def build_workspace(
    *,
    objects: list[dict[str, Any]],
    target_repo: str,
    document: str,
    validated: bool,
    failure: dict[str, Any] | None = None,
    selected_id: str | None = None,
) -> dict[str, Any]:
    chosen_id = _preferred_selected_id(objects, failure, selected_id)
    chosen = next((obj for obj in objects if _sid(obj) == chosen_id), objects[0] if objects else {})
    problem = None
    if failure:
        problem = {
            "title": str(failure.get("title", "Validation failed")),
            "summary": "Start with the safest recommended fix, then review the impact.",
            "primary_id": str(failure.get("primary_id", "")).strip(),
            "secondary_id": str(failure.get("secondary_id", "")).strip(),
            "actions": list(failure.get("actions") or []),
            "failure_code": str(failure.get("failure_code", "")).strip(),
            "error_text": str(failure.get("error_text", "")).strip(),
        }
    return {
        "target_repo": target_repo,
        "document": document,
        "tasks": [
            {
                "id": task_id,
                "label": label,
                "description": desc,
                "active": task_id == "fix_problem" and bool(failure),
            }
            for task_id, label, desc in _TASKS
        ],
        "navigation": {
            "items": _navigation_items(objects, failure),
            "counts": {
                "objects": len(objects),
                "problems": 1 if failure else 0,
                "workflow": sum(1 for obj in objects if _kind(obj).startswith("workflow_")),
            },
        },
        "selected_id": _sid(chosen),
        "selected": {
            "id": _sid(chosen),
            "kind": _kind(chosen),
            "kind_label": _label(_kind(chosen)),
            "title": _title(chosen),
            "technical_id": _sid(chosen),
            "summary": _SUMMARIES.get(
                _kind(chosen),
                f"This {_label(_kind(chosen)).lower()} belongs to the authority corpus.",
            ),
            "local_fields": _local_fields(chosen),
            "relation_sections": _relation_sections(chosen, objects),
            "manual_actions": _manual_actions(chosen),
        },
        "health": _health(validated, failure, len(objects)),
        "current_problem": problem,
        "technical_available": True,
    }
