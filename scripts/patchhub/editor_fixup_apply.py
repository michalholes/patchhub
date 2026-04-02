from __future__ import annotations

from copy import deepcopy
from typing import Any

from .editor_codec import recompute_meta_counts, scaffold_object
from .editor_fixup_shared import CLIENT_ONLY_ACTIONS, EditorFixupError


def _sid(obj: dict[str, Any]) -> str:
    return str(obj.get("id", "")).strip()


def _by_id(items: list[dict[str, Any]], obj_id: str) -> dict[str, Any] | None:
    return next((obj for obj in items if _sid(obj) == obj_id), None)


def _obj(items: list[dict[str, Any]], obj_id: str) -> dict[str, Any]:
    obj = _by_id(items, obj_id)
    if obj is None:
        raise EditorFixupError(f"Object not found: {obj_id}")
    return obj


def _items(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [obj for obj in items if obj.get("type") == kind]


def _str_list(values: Any) -> list[str]:
    return [str(x) for x in values]


def _swap(values: Any, old: str, new: str) -> list[str]:
    return [new if str(x) == old else str(x) for x in values]


def _drop(values: Any, old: str) -> list[str]:
    return [str(x) for x in values if str(x) != old]


def _remove(items: list[dict[str, Any]], obj_id: str) -> None:
    items[:] = [obj for obj in items if _sid(obj) != obj_id]


def _replace(items: list[dict[str, Any]], obj_id: str, new_obj: dict[str, Any]) -> None:
    for idx, obj in enumerate(items):
        if _sid(obj) == obj_id:
            items[idx] = new_obj
            return
    raise EditorFixupError(f"Object not found: {obj_id}")


def _unique(items: list[dict[str, Any]], base: str) -> str:
    used = {_sid(obj) for obj in items}
    if base not in used:
        return base
    idx = 1
    while f"{base}.{idx}" in used:
        idx += 1
    return f"{base}.{idx}"


def _append(items: list[dict[str, Any]], kind: str, preferred_id: str) -> dict[str, Any]:
    obj = deepcopy(scaffold_object(kind))
    obj["id"] = _unique(items, preferred_id or str(obj.get("id", kind.upper() + ".NEW")))
    items.append(obj)
    return obj


def _first(items: list[dict[str, Any]], kind: str, *, route_ref: str = "") -> dict[str, Any]:
    matches = [obj for obj in items if obj.get("type") == kind]
    if route_ref:
        matches = [obj for obj in matches if str(obj.get("route_ref", "")) == route_ref]
    if not matches:
        raise EditorFixupError(f"No matching {kind} object found")
    return sorted(matches, key=_sid)[0]


def _first_id(items: list[dict[str, Any]], kind: str) -> str:
    return _sid(_first(items, kind))


def _set_route_ref(obj: dict[str, Any], route_id: str) -> None:
    field = {
        "surface": "route_ref",
        "implementation": "implements_route",
        "workflow_step": "route_ref",
    }.get(str(obj.get("type", "")))
    if field is None:
        raise EditorFixupError("Object does not carry a route reference")
    obj[field] = route_id


FixContext = tuple[str, str, list[dict[str, Any]]]


def apply_fix_action(
    *,
    action_id: str,
    objects: list[dict[str, Any]],
    primary_id: str,
    secondary_id: str,
    loaded_objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if action_id in CLIENT_ONLY_ACTIONS:
        raise EditorFixupError(f"Action {action_id} is client-side only")
    items = deepcopy(objects)
    ctx = (primary_id.strip(), secondary_id.strip(), deepcopy(loaded_objects))
    _apply(items, ctx, action_id)
    recompute_meta_counts(items)
    return items


def _providers(items: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        obj
        for pid in map(str, route.get("provider_chain", []))
        if (obj := _by_id(items, pid)) is not None
    ]


def _missing_cap_id(items: list[dict[str, Any]], primary_id: str) -> str:
    primary = _by_id(items, primary_id)
    field = (
        "requires_capabilities"
        if primary and primary.get("type") == "surface"
        else "covers_capabilities"
    )
    for cap_id in (primary or {}).get(field, []):
        if _by_id(items, str(cap_id)) is None:
            return str(cap_id)
    return "CAP.FIX"


def _apply(items: list[dict[str, Any]], ctx: FixContext, action_id: str) -> None:
    primary_id, secondary_id, loaded_objects = ctx
    if action_id == "delete_unsaved_block":
        _remove(items, primary_id)
    elif action_id == "rename_current_id":
        _obj(items, primary_id)["id"] = _unique(items, primary_id + ".RENAMED")
    elif action_id == "revert_block":
        _replace(items, primary_id, deepcopy(_obj(loaded_objects, primary_id)))
    elif action_id in {"recreate_meta_block", "restore_last_loaded_meta"}:
        meta = next((obj for obj in loaded_objects if obj.get("type") == "meta"), None)
        items[:] = [obj for obj in items if obj.get("type") != "meta"]
        replacement = scaffold_object("meta") if action_id == "recreate_meta_block" else meta
        items.insert(0, deepcopy(replacement or scaffold_object("meta")))
    elif action_id == "merge_into_existing_binding_meta":
        keep_id = secondary_id or _first_id(items, "binding_meta")
        kept, seen = [], False
        for obj in items:
            if obj.get("type") != "binding_meta":
                kept.append(obj)
            elif not seen and str(obj.get("id", "")) == keep_id:
                kept.append(obj)
                seen = True
        items[:] = kept
    elif action_id == "create_binding_meta_block":
        _append(items, "binding_meta", "BINDING_META.NEW")
        items.insert(1 if items and items[0].get("type") == "meta" else 0, items.pop())
    elif action_id == "recompute_meta_counts":
        return
    elif action_id == "relink_rule_to_existing_capability":
        cap = _first(items, "capability")
        refs = [str(x) for x in cap.get("triggers_rules", [])]
        if primary_id not in refs:
            refs.append(primary_id)
        cap["triggers_rules"] = refs
    elif action_id == "create_companion_capability_block":
        cap = _append(items, "capability", "CAP.FIX")
        cap["triggers_rules"] = [primary_id]
        cap["name"] = primary_id
    elif action_id == "create_missing_rule_block":
        rule = _append(items, "rule", secondary_id or "RULE.FIX")
        rule["statement"] = f"Auto-created rule for {primary_id or rule['id']}"
    elif action_id == "relink_capability_rule_ref":
        cap = _obj(items, primary_id)
        rid = _first_id(items, "rule")
        cap["triggers_rules"] = _swap(cap.get("triggers_rules", []), secondary_id, rid)
    elif action_id == "remove_broken_rule_ref":
        cap = _obj(items, primary_id)
        cap["triggers_rules"] = _drop(cap.get("triggers_rules", []), secondary_id)
    elif action_id == "create_missing_capability_block":
        cap = _append(items, "capability", secondary_id or _missing_cap_id(items, primary_id))
        cap["name"] = cap["id"]
    elif action_id == "relink_route_capability_ref":
        route = _obj(items, primary_id)
        cid = _first_id(items, "capability")
        route["covers_capabilities"] = _swap(
            route.get("covers_capabilities", []),
            secondary_id,
            cid,
        )
    elif action_id == "remove_broken_route_capability_ref":
        route = _obj(items, primary_id)
        route["covers_capabilities"] = _drop(route.get("covers_capabilities", []), secondary_id)
    elif action_id == "add_provider_capability_coverage":
        route = _obj(items, primary_id)
        chain = _str_list(route.get("provider_chain", []))
        if not chain:
            raise EditorFixupError("Route has no provider_chain")
        provider = _obj(items, chain[-1])
        provided_caps = _str_list(provider.get("provides_capabilities", []))
        for cap_id in route.get("covers_capabilities", []):
            if str(cap_id) not in provided_caps:
                provided_caps.append(str(cap_id))
        provider["provides_capabilities"] = provided_caps
    elif action_id == "create_provider_block":
        route = _obj(items, primary_id)
        provider = _append(items, "provider", "PROVIDER.FIX")
        provider["provides_capabilities"] = [str(x) for x in route.get("covers_capabilities", [])]
        route["provider_chain"] = [*map(str, route.get("provider_chain", [])), provider["id"]]
    elif action_id == "reduce_route_capabilities":
        route = _obj(items, primary_id)
        provided_ids = {
            str(x) for obj in _providers(items, route) for x in obj.get("provides_capabilities", [])
        }
        route["covers_capabilities"] = [
            cap for cap in map(str, route.get("covers_capabilities", [])) if cap in provided_ids
        ]
    elif action_id in {"select_existing_route_ref", "create_route_block"}:
        if action_id == "create_route_block":
            route = _append(items, "route", secondary_id or primary_id or "ROUTE.FIX")
            _set_route_ref(_obj(items, primary_id), route["id"])
        else:
            _set_route_ref(_obj(items, primary_id), _first_id(items, "route"))
    elif action_id == "select_existing_capabilities":
        surface = _obj(items, primary_id)
        route_obj = _by_id(items, str(surface.get("route_ref", "")))
        cap_ids = [
            str(x)
            for x in (route_obj or {}).get("covers_capabilities", [])
            if _by_id(items, str(x))
        ]
        surface["requires_capabilities"] = cap_ids or sorted(
            str(obj.get("id", "")) for obj in _items(items, "capability")
        )
    elif action_id == "add_missing_declared_capabilities":
        impl = _obj(items, primary_id)
        route = _obj(items, str(impl.get("implements_route", "")))
        declared = _str_list(impl.get("declared_capabilities", []))
        for cap_id in route.get("covers_capabilities", []):
            if str(cap_id) not in declared:
                declared.append(str(cap_id))
        impl["declared_capabilities"] = declared
    elif action_id in {"select_existing_oracle_ref", "create_oracle_block"}:
        if action_id == "create_oracle_block":
            oracle = _append(items, "oracle", secondary_id or "ORACLE.FIX")
            _obj(items, primary_id)["oracle_ref"] = oracle["id"]
        else:
            _obj(items, primary_id)["oracle_ref"] = _first_id(items, "oracle")
    elif action_id == "clear_current_entry_fields":
        step = _obj(items, primary_id)
        step["entry_scope"] = ""
        step["entry_mode"] = ""
    elif action_id == "create_transition_block":
        sid = str(_obj(items, primary_id).get("id", ""))
        steps = sorted(_items(items, "workflow_step"), key=lambda obj: str(obj.get("id", "")))
        other = next((obj for obj in steps if str(obj.get("id", "")) != sid), None)
        if other is None:
            raise EditorFixupError("At least two workflow steps are required")
        inbound = any(
            str(obj.get("to_step", "")) == sid for obj in _items(items, "workflow_transition")
        )
        trans = _append(items, "workflow_transition", "WORKFLOW_TRANSITION.FIX")
        other_id = str(other.get("id", ""))
        trans["from_step"], trans["to_step"] = (sid, other_id) if inbound else (other_id, sid)
    elif action_id == "create_invalidation_block":
        steps = sorted(_items(items, "workflow_step"), key=lambda obj: str(obj.get("id", "")))
        target = next(
            (
                obj
                for obj in steps
                if str(obj.get("id", "")) != primary_id and obj.get("root_marker")
            ),
            None,
        )
        target = target or next(
            (obj for obj in steps if str(obj.get("id", "")) != primary_id),
            None,
        )
        if target is None:
            raise EditorFixupError("No invalidation target available")
        inv = _append(items, "workflow_invalidation", "WORKFLOW_INVALIDATION.FIX")
        inv["failing_step"] = primary_id
        inv["invalidates_step"] = str(target.get("id", ""))
    elif action_id == "create_rollback_block":
        target = next(
            (obj for obj in _items(items, "workflow_step") if obj.get("root_marker")),
            None,
        )
        if target is None:
            raise EditorFixupError("No rollback target available")
        rb = _append(items, "workflow_rollback", "WORKFLOW_ROLLBACK.FIX")
        rb["from_step"] = primary_id
        rb["rollback_to_step"] = str(target.get("id", ""))
    elif action_id == "clear_rollback_required_flag":
        _obj(items, primary_id)["rollback_required"] = False
    elif action_id == "create_entry_gate_block":
        step = _obj(items, primary_id)
        gate = _append(items, "workflow_gate", "WORKFLOW_GATE.FIX")
        gate["step_ref"] = primary_id
        gate["gate_kind"] = "entry"
        gate["gate_capabilities"] = [str(x) for x in step.get("required_capabilities", [])]
        gate["gate_rule_ids"] = []
    elif action_id == "mark_workflow_step_root":
        step = _obj(items, primary_id)
        step["root_marker"] = True
        if not str(step.get("entry_scope", "")).strip():
            step["entry_scope"] = "implementation_scope"
        if not str(step.get("entry_mode", "")).strip():
            step["entry_mode"] = "final"
    elif action_id in {"create_workflow_step_for_surface", "create_workflow_step_for_route"}:
        source = _obj(items, primary_id)
        step = _append(items, "workflow_step", "WORKFLOW_STEP.FIX")
        if action_id.endswith("surface"):
            surface_id, route_id = primary_id, str(source.get("route_ref", ""))
            req_caps = [str(x) for x in source.get("requires_capabilities", [])]
        else:
            surface_id = str(_first(items, "surface", route_ref=primary_id).get("id", ""))
            route_id = primary_id
            req_caps = _str_list(source.get("covers_capabilities", []))
        step.update(
            {
                "display_name": primary_id,
                "branch": "editor_fix",
                "route_ref": route_id,
                "surface_ref": surface_id,
                "required_capabilities": req_caps,
            }
        )
    elif action_id == "relink_workflow_step_surface":
        step = _obj(items, primary_id)
        step["surface_ref"] = str(
            _first(
                items,
                "surface",
                route_ref=str(step.get("route_ref", "")),
            ).get("id", "")
        )
    elif action_id == "relink_workflow_step_route":
        step = _obj(items, primary_id)
        step["route_ref"] = str(_obj(items, str(step.get("surface_ref", ""))).get("route_ref", ""))
    else:
        raise EditorFixupError(f"Unknown action_id: {action_id}")
