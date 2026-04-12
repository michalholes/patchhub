from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .app_support import _err, _ok
from .editor_action_preview import preview_action
from .editor_codec import (
    DOCUMENT_PATHS,
    FORMAT_NAME,
    OBJECT_TYPE_ORDER,
    document_relpath,
    human_text_from_jsonl_text,
    human_text_from_objects,
    jsonl_text_from_objects,
    parse_human_text,
    parse_jsonl_text,
    recompute_meta_counts,
    scaffold_object,
    validate_human_text,
)
from .editor_fixup_apply import apply_fix_action
from .editor_fixup_shared import CLIENT_ONLY_ACTIONS, EditorFixupError
from .editor_fixups import build_failure, empty_failure
from .editor_workspace import build_workspace
from .governance_toolkit_runtime import (
    GovernanceToolkitRuntimeError,
    GovernanceToolkitSelection,
    resolve_governance_toolkit,
)
from .targeting import resolve_targeting_runtime, validate_selected_target_repo

DOC_OPTIONS = OrderedDict(
    {
        "specification": DOCUMENT_PATHS["specification"],
        "governance": DOCUMENT_PATHS["governance"],
    }
)
OPS_LEVELS = ["(all)", "Info", "Warning", "Error"]
OPS_CODES = {
    "LOAD_START",
    "LOAD_OK",
    "LOAD_FAIL",
    "DIRTY_STATE",
    "VALIDATE_START",
    "VALIDATE_OK",
    "VALIDATE_FAIL",
    "SAVE_START",
    "SAVE_OK",
    "SAVE_FAIL",
    "UNSAFE_CONFIRM_OPEN",
    "UNSAFE_SAVE_START",
    "UNSAFE_SAVE_OK",
    "UNSAFE_SAVE_FAIL",
    "FIX_APPLY",
    "FIX_FAIL",
    "TOOLKIT_START",
    "TOOLKIT_OK",
    "TOOLKIT_FAIL",
}
UNSAFE_WARNING = (
    "Unsafe save bypasses semantic validation and may persist an invalid authority file. Continue?"
)


@dataclass
class RevisionState:
    target_repo: str
    document: str
    loaded_text: str
    loaded_objects: list[dict[str, Any]]
    current_text: str
    toolkit_selection: GovernanceToolkitSelection | None
    toolkit_resolution: dict[str, Any]


_REVISION_CACHE: OrderedDict[str, RevisionState] = OrderedDict()
_REVISION_LOCK = threading.Lock()
_MAX_REVISIONS = 64


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _op(level: str, code: str, message: str) -> dict[str, str]:
    if level not in {"Info", "Warning", "Error"} or code not in OPS_CODES:
        raise ValueError("Unsupported editor op")
    return {"ts": _now(), "level": level, "code": code, "message": str(message)}


def _store_state(
    *,
    target_repo: str,
    document: str,
    loaded_text: str,
    loaded_objects: list[dict[str, Any]],
    current_text: str,
    toolkit_selection: GovernanceToolkitSelection | None = None,
) -> tuple[str, RevisionState]:
    raw = f"{target_repo}\0{document}\0{loaded_text}\0{current_text}".encode()
    token = hashlib.sha256(raw).hexdigest()
    state = RevisionState(
        target_repo=target_repo,
        document=document,
        loaded_text=loaded_text,
        loaded_objects=deepcopy(loaded_objects),
        current_text=current_text,
        toolkit_selection=toolkit_selection,
        toolkit_resolution=(
            dict(toolkit_selection.resolution) if toolkit_selection is not None else {}
        ),
    )
    with _REVISION_LOCK:
        _REVISION_CACHE[token] = state
        _REVISION_CACHE.move_to_end(token)
        while len(_REVISION_CACHE) > _MAX_REVISIONS:
            _REVISION_CACHE.popitem(last=False)
    return token, state


def _state(token: str, target_repo: str, document: str) -> RevisionState | None:
    with _REVISION_LOCK:
        state = _REVISION_CACHE.get(str(token or "").strip())
    if state and state.target_repo == target_repo and state.document == document:
        return state
    return None


def _runtime(self: Any):
    return resolve_targeting_runtime(
        repo_root=self.repo_root,
        runner_config_toml=self.cfg.runner.runner_config_toml,
        target_cfg=getattr(self.cfg, "targeting", None),
    )


def _target_root(self: Any, target_repo: str) -> Path:
    runtime = _runtime(self)
    token = validate_selected_target_repo(target_repo, runtime.options)
    root = runtime.resolved_roots_by_token.get(token)
    if root is None:
        raise ValueError("target_repo root missing")
    return Path(root)


def _doc_path(self: Any, target_repo: str, document: str) -> Path:
    root = _target_root(self, target_repo)
    path = (root / document_relpath(document)).resolve()
    if root not in path.parents:
        raise ValueError("document path escapes target root")
    return path


def _require_existing_doc(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Target file does not exist: {path}")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
        fh.write(text)
        fh.flush()
        tmp = fh.name
    Path(tmp).replace(path)


def _persist(
    target_repo: str,
    document: str,
    state: RevisionState | None,
    human_text: str,
    objects: list[dict[str, Any]],
    *,
    loaded_text: str | None = None,
    toolkit_selection: GovernanceToolkitSelection | None = None,
):
    return _store_state(
        target_repo=target_repo,
        document=document,
        loaded_text=(
            loaded_text if loaded_text is not None else (state.loaded_text if state else human_text)
        ),
        loaded_objects=state.loaded_objects if state else objects,
        current_text=human_text,
        toolkit_selection=(
            toolkit_selection
            if toolkit_selection is not None
            else state.toolkit_selection
            if state
            else None
        ),
    )


def _workspace_payload(
    *,
    target_repo: str,
    document: str,
    objects: list[dict[str, Any]],
    validated: bool,
    failure: dict[str, Any] | None = None,
    selected_id: str | None = None,
) -> dict[str, Any]:
    return build_workspace(
        objects=objects,
        target_repo=target_repo,
        document=document,
        validated=validated,
        failure=failure,
        selected_id=selected_id,
    )


def _validate_current(
    *,
    validator_path: Path,
    human_text: str,
    loaded_objects: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    return validate_human_text(
        validator_path=validator_path,
        human_text=human_text,
        loaded_objects=loaded_objects,
        failure_builder=build_failure,
    )


def _toolkit_status_message(selection: GovernanceToolkitSelection) -> str:
    record = selection.resolution
    selected = str(record.get("selected_sig", "")).strip()
    mode = str(record.get("resolution_mode", "")).strip()
    cache_hit = bool(record.get("cache_hit", False))
    download_performed = bool(record.get("download_performed", False))
    return (
        f"Toolkit selected {selected or '(unknown)'}"
        f" mode={mode or '(unknown)'}"
        f" cache_hit={str(cache_hit).lower()}"
        f" download={str(download_performed).lower()}"
    )


def _toolkit_failure_message(resolution: dict[str, Any]) -> str:
    selected = str(resolution.get("selected_sig", "")).strip()
    mode = str(resolution.get("resolution_mode", "")).strip()
    error = str(resolution.get("error", "")).strip()
    return (
        f"Toolkit resolution failed selected={selected or '(none)'}"
        f" mode={mode or '(unknown)'} error={error or '(unknown)'}"
    )


def _missing_revision_failure(kind: str, message: str) -> dict[str, Any]:
    return empty_failure(kind, message)


def _scaffold_text_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for object_type in OBJECT_TYPE_ORDER:
        obj = deepcopy(scaffold_object(object_type))
        recompute_meta_counts([obj])
        out[object_type] = human_text_from_objects([obj])
    return out


def api_editor_bootstrap(self: Any, qs: dict[str, str] | None = None) -> tuple[int, bytes]:
    try:
        runtime = _runtime(self)
    except (OSError, ValueError) as exc:
        return _err(str(exc), status=400)
    return _ok(
        {
            "target_repo": runtime.default_target_repo,
            "target_repo_options": runtime.options,
            "documents": [{"value": k, "path": v} for k, v in DOC_OPTIONS.items()],
            "default_document": "specification",
            "format_name": FORMAT_NAME,
            "ops_levels": OPS_LEVELS,
            "unsafe_warning": UNSAFE_WARNING,
            "add_type_options": OBJECT_TYPE_ORDER,
            "scaffolds": _scaffold_text_map(),
        }
    )


def api_editor_document(self: Any, qs: dict[str, str] | None = None) -> tuple[int, bytes]:
    qs = qs or {}
    target_repo = str(qs.get("target_repo", "")).strip()
    document = str(qs.get("document", "")).strip()
    ops = [_op("Info", "LOAD_START", f"Loading {document}")]
    toolkit_resolution: dict[str, Any] = {}
    try:
        ops.append(_op("Info", "TOOLKIT_START", f"Resolving toolkit for {document}"))
        toolkit = resolve_governance_toolkit(self.cfg)
        toolkit_resolution = dict(toolkit.resolution)
        ops.append(_op("Info", "TOOLKIT_OK", _toolkit_status_message(toolkit)))
        path = _doc_path(self, target_repo, document)
        raw = path.read_text(encoding="utf-8")
        human = human_text_from_jsonl_text(raw)
        objects = parse_jsonl_text(raw)
        token, state = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=human,
            loaded_objects=objects,
            current_text=human,
            toolkit_selection=toolkit,
        )
        ok, validated_objects, failure = _validate_current(
            validator_path=toolkit.validate_master_spec_v2_path,
            human_text=human,
            loaded_objects=state.loaded_objects,
        )
        workspace = _workspace_payload(
            target_repo=target_repo,
            document=document,
            objects=validated_objects if ok else state.loaded_objects,
            validated=ok,
            failure=failure,
        )
        ops.append(_op("Info", "LOAD_OK", f"Loaded {path.name}"))
        return _ok(
            {
                "target_repo": target_repo,
                "document": document,
                "document_path": document_relpath(document),
                "revision_token": token,
                "human_text": human,
                "format_name": FORMAT_NAME,
                "status": "Loaded",
                "last_action_state": "Loaded",
                "dirty_state": "clean",
                "add_type_options": OBJECT_TYPE_ORDER,
                "loaded_ids": [str(obj.get("id", "")) for obj in state.loaded_objects],
                "workspace": workspace,
                "validated": ok,
                "failure": failure,
                "toolkit_resolution": toolkit_resolution,
                "ops": ops,
            }
        )
    except GovernanceToolkitRuntimeError as exc:
        toolkit_resolution = dict(exc.resolution)
        ops.append(_op("Error", "TOOLKIT_FAIL", _toolkit_failure_message(toolkit_resolution)))
        return _err(
            json.dumps(
                {
                    "ops": ops,
                    "error": str(exc),
                    "toolkit_resolution": toolkit_resolution,
                }
            ),
            status=400,
        )
    except Exception as exc:
        ops.append(_op("Error", "LOAD_FAIL", str(exc)))
        return _err(
            json.dumps(
                {
                    "ops": ops,
                    "error": str(exc),
                    "toolkit_resolution": toolkit_resolution,
                }
            ),
            status=400,
        )


def api_editor_validate(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "VALIDATE_START", f"Validating {document}")]
    if state is None or state.toolkit_selection is None:
        failed = _missing_revision_failure(
            "missing_revision_state",
            "Missing or stale revision_token",
        )
        ops.append(_op("Error", "VALIDATE_FAIL", failed["failure_code"]))
        return _ok(
            {
                "validated": False,
                "failure": failed,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=[],
                    validated=False,
                    failure=failed,
                ),
                "toolkit_resolution": {},
                "last_action_state": "Validation failed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )
    ops.append(_op("Info", "TOOLKIT_OK", _toolkit_status_message(state.toolkit_selection)))
    try:
        ok, objects, failure = _validate_current(
            validator_path=state.toolkit_selection.validate_master_spec_v2_path,
            human_text=human_text,
            loaded_objects=state.loaded_objects,
        )
        if not ok:
            failed = failure or empty_failure("validate_failure", "Validation failed")
            ops.append(_op("Error", "VALIDATE_FAIL", failed["failure_code"]))
            return _ok(
                {
                    "validated": False,
                    "failure": failed,
                    "workspace": _workspace_payload(
                        target_repo=target_repo,
                        document=document,
                        objects=state.loaded_objects,
                        validated=False,
                        failure=failed,
                    ),
                    "toolkit_resolution": state.toolkit_resolution,
                    "last_action_state": "Validation failed",
                    "dirty_state": "dirty",
                    "ops": ops,
                }
            )
        token, _ = _persist(
            target_repo,
            document,
            state,
            human_text,
            objects,
            toolkit_selection=state.toolkit_selection,
        )
        ops.append(_op("Info", "VALIDATE_OK", "Validation passed"))
        return _ok(
            {
                "validated": True,
                "revision_token": token,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=objects,
                    validated=True,
                    failure=None,
                ),
                "toolkit_resolution": state.toolkit_resolution,
                "last_action_state": "Validation passed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "VALIDATE_FAIL", str(exc)))
        failed = empty_failure("validate_exception", str(exc))
        return _ok(
            {
                "validated": False,
                "failure": failed,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=state.loaded_objects,
                    validated=False,
                    failure=failed,
                ),
                "toolkit_resolution": state.toolkit_resolution,
                "last_action_state": "Validation failed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )


def api_editor_save(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "SAVE_START", f"Saving {document}")]
    if state is None or state.toolkit_selection is None:
        failed = _missing_revision_failure(
            "missing_revision_state",
            "Missing or stale revision_token",
        )
        ops.append(_op("Error", "SAVE_FAIL", failed["failure_code"]))
        return _ok(
            {
                "saved": False,
                "failure": failed,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=[],
                    validated=False,
                    failure=failed,
                ),
                "toolkit_resolution": {},
                "last_action_state": "Save failed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )
    ops.append(_op("Info", "TOOLKIT_OK", _toolkit_status_message(state.toolkit_selection)))
    try:
        ok, objects, failure = _validate_current(
            validator_path=state.toolkit_selection.validate_master_spec_v2_path,
            human_text=human_text,
            loaded_objects=state.loaded_objects,
        )
        if not ok:
            failed = failure or empty_failure("save_failure", "Save failed")
            ops.append(_op("Error", "SAVE_FAIL", failed["failure_code"]))
            return _ok(
                {
                    "saved": False,
                    "failure": failed,
                    "workspace": _workspace_payload(
                        target_repo=target_repo,
                        document=document,
                        objects=state.loaded_objects,
                        validated=False,
                        failure=failed,
                    ),
                    "toolkit_resolution": state.toolkit_resolution,
                    "ops": ops,
                }
            )
        path = _doc_path(self, target_repo, document)
        _require_existing_doc(path)
        _write_text(path, jsonl_text_from_objects(objects))
        normalized = human_text_from_objects(objects)
        token, _ = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=normalized,
            loaded_objects=objects,
            current_text=normalized,
            toolkit_selection=state.toolkit_selection,
        )
        ops.append(_op("Info", "SAVE_OK", f"Saved {path.name}"))
        return _ok(
            {
                "saved": True,
                "revision_token": token,
                "human_text": normalized,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=objects,
                    validated=True,
                    failure=None,
                ),
                "toolkit_resolution": state.toolkit_resolution,
                "last_action_state": "Saved",
                "dirty_state": "clean",
                "ops": ops,
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "SAVE_FAIL", str(exc)))
        failed = empty_failure("save_exception", str(exc))
        return _ok(
            {
                "saved": False,
                "failure": failed,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=state.loaded_objects,
                    validated=False,
                    failure=failed,
                ),
                "toolkit_resolution": state.toolkit_resolution,
                "last_action_state": "Save failed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )


def api_editor_save_unsafe(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    confirmed = bool(body.get("confirm_unsafe_write") is True)
    ops = [_op("Warning", "UNSAFE_SAVE_START", f"Unsafe save for {document}")]
    toolkit_resolution = state.toolkit_resolution if state else {}
    try:
        if not confirmed:
            raise ValueError("Unsafe save requires explicit confirmation")
        parsed = parse_human_text(human_text)
        path = _doc_path(self, target_repo, document)
        _require_existing_doc(path)
        _write_text(path, jsonl_text_from_objects(parsed.objects))
        normalized = human_text_from_objects(parsed.objects)
        token, _ = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=normalized,
            loaded_objects=parsed.objects,
            current_text=normalized,
            toolkit_selection=(state.toolkit_selection if state else None),
        )
        ops.append(_op("Warning", "UNSAFE_SAVE_OK", f"Saved {path.name} without validation"))
        return _ok(
            {
                "saved": True,
                "revision_token": token,
                "human_text": normalized,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=parsed.objects,
                    validated=False,
                    failure=None,
                ),
                "toolkit_resolution": toolkit_resolution,
                "last_action_state": "Unsafe save complete",
                "dirty_state": "clean",
                "ops": ops,
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "UNSAFE_SAVE_FAIL", str(exc)))
        failed = empty_failure("unsafe_save_exception", str(exc))
        try:
            fallback_objects = parse_human_text(human_text).objects if human_text else []
        except Exception:
            fallback_objects = []
        return _ok(
            {
                "saved": False,
                "failure": failed,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=fallback_objects,
                    validated=False,
                    failure=failed,
                ),
                "toolkit_resolution": toolkit_resolution,
                "last_action_state": "Unsafe save failed",
                "dirty_state": "dirty",
                "ops": ops,
            }
        )


def api_editor_preview_action(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    action_id = str(body.get("action_id", "")).strip()
    primary_id = str(body.get("primary_id", "")).strip()
    secondary_id = str(body.get("secondary_id", "")).strip()
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "FIX_APPLY", f"PREVIEW:{action_id}")]
    try:
        loaded_objects = state.loaded_objects if state else []
        current_objects = parse_human_text(str(body.get("human_text", ""))).objects
        preview, fixed = preview_action(
            action_id=action_id,
            objects=current_objects,
            loaded_objects=loaded_objects,
            primary_id=primary_id,
            secondary_id=secondary_id,
        )
        if state is None or state.toolkit_selection is None:
            failure = _missing_revision_failure(
                "missing_revision_state",
                "Missing or stale revision_token",
            )
            preview["post_validation"] = {"validated": False, "failure": failure}
            return _ok({"ok": True, "preview": preview, "ops": ops})
        ok, _objects, validation_failure = _validate_current(
            validator_path=state.toolkit_selection.validate_master_spec_v2_path,
            human_text=human_text_from_objects(fixed),
            loaded_objects=loaded_objects,
        )
        preview["post_validation"] = {"validated": ok, "failure": validation_failure}
        return _ok({"ok": True, "preview": preview, "ops": ops})
    except Exception as exc:
        ops.append(_op("Error", "FIX_FAIL", str(exc)))
        return _ok({"ok": False, "error": str(exc), "ops": ops})


def api_editor_apply_fix(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    required = {
        "target_repo",
        "document",
        "revision_token",
        "human_text",
        "action_id",
        "primary_id",
        "secondary_id",
    }
    if set(body) != required:
        return _err(f"apply_fix payload keys must be exactly {sorted(required)}", status=400)
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    action_id = str(body.get("action_id", "")).strip()
    primary_id = str(body.get("primary_id", "")).strip()
    secondary_id = str(body.get("secondary_id", "")).strip()
    if action_id in CLIENT_ONLY_ACTIONS:
        return _err("Client-side action must not call apply_fix", status=400)
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "FIX_APPLY", action_id)]
    try:
        if state is None or state.toolkit_selection is None:
            raise EditorFixupError("Unknown revision_token")
        fixed = apply_fix_action(
            action_id=action_id,
            objects=parse_human_text(str(body.get("human_text", ""))).objects,
            primary_id=primary_id,
            secondary_id=secondary_id,
            loaded_objects=state.loaded_objects,
        )
        human = human_text_from_objects(fixed)
        ok, _objects, failure = validate_human_text(
            validator_path=state.toolkit_selection.validate_master_spec_v2_path,
            human_text=human,
            loaded_objects=state.loaded_objects,
            failure_builder=build_failure,
        )
        token, _ = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=state.loaded_text,
            loaded_objects=state.loaded_objects,
            current_text=human,
            toolkit_selection=state.toolkit_selection,
        )
        return _ok(
            {
                "ok": True,
                "human_text": human,
                "revision_token": token,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=fixed,
                    validated=ok,
                    failure=failure,
                    selected_id=primary_id or secondary_id,
                ),
                "ops": ops,
                "toolkit_resolution": state.toolkit_resolution,
                "validation": {"validated": ok, "failure": failure},
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "FIX_FAIL", str(exc)))
        failed = empty_failure(
            "fix_exception",
            str(exc),
            primary_id=primary_id,
            secondary_id=secondary_id,
        )
        return _ok(
            {
                "ok": False,
                "workspace": _workspace_payload(
                    target_repo=target_repo,
                    document=document,
                    objects=state.loaded_objects if state else [],
                    validated=False,
                    failure=failed,
                    selected_id=primary_id or secondary_id,
                ),
                "ops": ops,
                "toolkit_resolution": (state.toolkit_resolution if state is not None else {}),
                "validation": {
                    "validated": False,
                    "failure": failed,
                },
            }
        )
