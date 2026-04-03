from __future__ import annotations

import json
from typing import Any

from .editor_fixup_apply import apply_fix_action
from .editor_fixup_shared import CLIENT_ONLY_ACTIONS, EditorFixupError

_ACTION_TITLES = {
    "rename_current_id": "Rename the selected id",
    "delete_unsaved_block": "Delete the selected block",
    "select_existing_route_ref": "Relink to an existing route",
    "select_existing_oracle_ref": "Relink to an existing oracle",
    "select_existing_capabilities": "Align required abilities",
}


def _sid(obj: dict[str, Any]) -> str:
    return str(obj.get("id", "")).strip()


def _title(action_id: str) -> str:
    return _ACTION_TITLES.get(action_id, f"Preview action: {action_id}")


def _summary(action_id: str) -> str:
    if action_id == "rename_current_id":
        return (
            "This changes the selected object id and may affect "
            "references that still point to the old id."
        )
    if action_id == "delete_unsaved_block":
        return (
            "This removes the selected block from the current workspace state before you save it."
        )
    if action_id == "select_existing_route_ref":
        return (
            "This switches the selected object to an existing route "
            "instead of creating a duplicate."
        )
    if action_id == "select_existing_oracle_ref":
        return (
            "This switches the binding to an existing oracle instead of leaving a broken reference."
        )
    if action_id == "select_existing_capabilities":
        return (
            "This replaces the current required abilities with the abilities "
            "covered by the linked route."
        )
    return (
        "This action changes the current workspace state and should be reviewed before applying it."
    )


def preview_action(
    *,
    action_id: str,
    objects: list[dict[str, Any]],
    loaded_objects: list[dict[str, Any]],
    primary_id: str,
    secondary_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if action_id in CLIENT_ONLY_ACTIONS:
        raise EditorFixupError(f"Action {action_id} is client-side only")
    before_index = {
        _sid(obj): json.dumps(obj, ensure_ascii=True, sort_keys=True) for obj in objects
    }
    fixed = apply_fix_action(
        action_id=action_id,
        objects=objects,
        primary_id=primary_id,
        secondary_id=secondary_id,
        loaded_objects=loaded_objects,
    )
    after_index = {_sid(obj): json.dumps(obj, ensure_ascii=True, sort_keys=True) for obj in fixed}
    added = sorted(set(after_index) - set(before_index))
    removed = sorted(set(before_index) - set(after_index))
    changed = sorted(
        obj_id
        for obj_id in sorted(set(before_index) & set(after_index))
        if before_index[obj_id] != after_index[obj_id]
    )
    affected = [
        obj_id
        for obj_id in [
            primary_id.strip(),
            secondary_id.strip(),
            *added,
            *removed,
            *changed,
        ]
        if obj_id
    ]
    preview = {
        "action_id": action_id,
        "title": _title(action_id),
        "summary": _summary(action_id),
        "consequences": [
            "Review the impact before applying it.",
            "The workspace summary will refresh after the action is applied.",
        ],
        "affected_objects": affected[:10],
        "technical": {
            "added": added,
            "removed": removed,
            "changed": changed,
            "counts": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
            },
        },
    }
    return preview, fixed
