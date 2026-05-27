from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass
class IssueState:
    base_sha: str
    allowed_union: set[str]


def _state_path(workspace_root: Path) -> Path:
    return workspace_root / ".am_patch_state.json"


def _coerce_state_dict(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    mapping = cast(dict[object, object], raw)
    out: dict[str, object] = {}
    for key, value in mapping.items():
        out[str(key)] = value
    return out


def load_state(workspace_root: Path, base_sha: str) -> IssueState:
    p = _state_path(workspace_root)
    if not p.exists():
        return IssueState(base_sha=base_sha, allowed_union=set())
    try:
        loaded = cast(object, json.loads(p.read_text(encoding="utf-8")))
        raw = _coerce_state_dict(loaded)
        if raw is None:
            return IssueState(base_sha=base_sha, allowed_union=set())
        base_value = raw.get("base_sha", "")
        st_base = base_value if isinstance(base_value, str) else str(base_value)
        allowed_raw = raw.get("allowed_union", [])
        allowed_items = cast(list[object], allowed_raw) if isinstance(allowed_raw, list) else []
        allowed = {str(item) for item in allowed_items if isinstance(item, str)}
        # If base_sha changed (workspace re-created / updated), reset union to avoid mixing bases.
        if st_base != base_sha:
            return IssueState(base_sha=base_sha, allowed_union=set())
        return IssueState(base_sha=base_sha, allowed_union=allowed)
    except Exception:
        # Corrupt state -> reset
        return IssueState(base_sha=base_sha, allowed_union=set())


def save_state(workspace_root: Path, state: IssueState) -> None:
    p = _state_path(workspace_root)
    data: dict[str, object] = {
        "base_sha": state.base_sha,
        "allowed_union": sorted(state.allowed_union),
    }
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_union(state: IssueState, files_current: list[str]) -> IssueState:
    for f in files_current:
        state.allowed_union.add(f)
    return state
