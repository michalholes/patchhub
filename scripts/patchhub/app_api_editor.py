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
    validate_human_text,
)
from .editor_fixups import (
    CLIENT_ONLY_ACTIONS,
    EditorFixupError,
    apply_fix_action,
    build_failure,
    empty_failure,
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
) -> tuple[str, RevisionState]:
    raw = f"{target_repo}\0{document}\0{loaded_text}\0{current_text}".encode()
    token = hashlib.sha256(raw).hexdigest()
    state = RevisionState(
        target_repo, document, loaded_text, deepcopy(loaded_objects), current_text
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
):
    return _store_state(
        target_repo=target_repo,
        document=document,
        loaded_text=(
            loaded_text if loaded_text is not None else (state.loaded_text if state else human_text)
        ),
        loaded_objects=state.loaded_objects if state else objects,
        current_text=human_text,
    )


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
        }
    )


def api_editor_document(self: Any, qs: dict[str, str] | None = None) -> tuple[int, bytes]:
    qs = qs or {}
    target_repo = str(qs.get("target_repo", "")).strip()
    document = str(qs.get("document", "")).strip()
    ops = [_op("Info", "LOAD_START", f"Loading {document}")]
    try:
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
                "status": "",
                "add_type_options": OBJECT_TYPE_ORDER,
                "loaded_ids": [str(obj.get("id", "")) for obj in state.loaded_objects],
                "ops": ops,
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "LOAD_FAIL", str(exc)))
        return _err(json.dumps({"ops": ops, "error": str(exc)}), status=400)


def api_editor_validate(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "VALIDATE_START", f"Validating {document}")]
    try:
        ok, objects, failure = validate_human_text(
            target_root=_target_root(self, target_repo),
            human_text=human_text,
            loaded_objects=state.loaded_objects if state else [],
            failure_builder=build_failure,
        )
        if not ok:
            failed = failure or empty_failure("validate_failure", "Validation failed")
            ops.append(_op("Error", "VALIDATE_FAIL", failed["failure_code"]))
            return _ok({"validated": False, "failure": failed, "ops": ops})
        token, _ = _persist(target_repo, document, state, human_text, objects)
        ops.append(_op("Info", "VALIDATE_OK", "Validation passed"))
        return _ok({"validated": True, "revision_token": token, "ops": ops})
    except Exception as exc:
        ops.append(_op("Error", "VALIDATE_FAIL", str(exc)))
        return _ok(
            {
                "validated": False,
                "failure": empty_failure("validate_exception", str(exc)),
                "ops": ops,
            }
        )


def api_editor_save(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    state = _state(str(body.get("revision_token", "")).strip(), target_repo, document)
    ops = [_op("Info", "SAVE_START", f"Saving {document}")]
    try:
        ok, objects, failure = validate_human_text(
            target_root=_target_root(self, target_repo),
            human_text=human_text,
            loaded_objects=state.loaded_objects if state else [],
            failure_builder=build_failure,
        )
        if not ok:
            failed = failure or empty_failure("save_failure", "Save failed")
            ops.append(_op("Error", "SAVE_FAIL", failed["failure_code"]))
            return _ok({"saved": False, "failure": failed, "ops": ops})
        path = _doc_path(self, target_repo, document)
        _write_text(path, jsonl_text_from_objects(objects))
        normalized = human_text_from_objects(objects)
        token, _ = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=normalized,
            loaded_objects=objects,
            current_text=normalized,
        )
        ops.append(_op("Info", "SAVE_OK", f"Saved {path.name}"))
        return _ok(
            {
                "saved": True,
                "revision_token": token,
                "human_text": normalized,
                "ops": ops,
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "SAVE_FAIL", str(exc)))
        return _ok(
            {
                "saved": False,
                "failure": empty_failure("save_exception", str(exc)),
                "ops": ops,
            }
        )


def api_editor_save_unsafe(self: Any, body: dict[str, Any]) -> tuple[int, bytes]:
    target_repo = str(body.get("target_repo", "")).strip()
    document = str(body.get("document", "")).strip()
    human_text = str(body.get("human_text", ""))
    ops = [_op("Warning", "UNSAFE_SAVE_START", f"Unsafe save for {document}")]
    try:
        parsed = parse_human_text(human_text)
        path = _doc_path(self, target_repo, document)
        _write_text(path, jsonl_text_from_objects(parsed.objects))
        normalized = human_text_from_objects(parsed.objects)
        token, _ = _store_state(
            target_repo=target_repo,
            document=document,
            loaded_text=normalized,
            loaded_objects=parsed.objects,
            current_text=normalized,
        )
        ops.append(_op("Warning", "UNSAFE_SAVE_OK", f"Saved {path.name} without validation"))
        return _ok({"saved": True, "revision_token": token, "human_text": normalized, "ops": ops})
    except Exception as exc:
        ops.append(_op("Error", "UNSAFE_SAVE_FAIL", str(exc)))
        return _ok(
            {
                "saved": False,
                "failure": empty_failure("unsafe_save_exception", str(exc)),
                "ops": ops,
            }
        )


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
        if state is None:
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
            target_root=_target_root(self, target_repo),
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
        )
        return _ok(
            {
                "ok": True,
                "human_text": human,
                "revision_token": token,
                "ops": ops,
                "validation": {"validated": ok, "failure": failure},
            }
        )
    except Exception as exc:
        ops.append(_op("Error", "FIX_FAIL", str(exc)))
        return _ok(
            {
                "ok": False,
                "ops": ops,
                "validation": {
                    "validated": False,
                    "failure": empty_failure(
                        "fix_exception",
                        str(exc),
                        primary_id=primary_id,
                        secondary_id=secondary_id,
                    ),
                },
            }
        )
