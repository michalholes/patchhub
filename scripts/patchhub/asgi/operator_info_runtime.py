from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import cast

_OPERATOR_INFO_RUNTIME_NAME = "patchhub_operator_info.json"
_RUNTIME_OPERATOR_INFO: dict[str, dict[str, object]] = {}


def _obj_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    raw_dict = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw_dict.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _obj_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(cast(list[object], value))
    return []


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def operator_info_runtime_path(patches_root: Path) -> Path:
    return patches_root / "artifacts" / _OPERATOR_INFO_RUNTIME_NAME


def _runtime_key(patches_root: Path) -> str:
    return str(patches_root)


def _empty_backend_mode_status() -> dict[str, object]:
    return {
        "mode": "",
        "authoritative_backend": "",
        "backend_session_id": "",
        "recovery_status": "not_run",
        "recovery_action": "",
        "recovery_detail": "",
        "degraded": False,
    }


def _empty_operator_info() -> dict[str, object]:
    return {
        "cleanup_recent_status": [],
        "backend_mode_status": _empty_backend_mode_status(),
    }


def _normalize_cleanup_item(item: object) -> dict[str, object] | None:
    item_obj = _obj_dict(item)
    if not item_obj:
        return None
    normalized_rules: list[dict[str, object]] = []
    for raw_rule in _obj_list(item_obj.get("rules")):
        rule = _obj_dict(raw_rule)
        if not rule:
            continue
        normalized_rules.append(
            {
                "filename_pattern": str(rule.get("filename_pattern", "")),
                "keep_count": _as_int(rule.get("keep_count", 0), 0),
                "matched_count": _as_int(rule.get("matched_count", 0), 0),
                "deleted_count": _as_int(rule.get("deleted_count", 0), 0),
            }
        )
    return {
        "job_id": str(item_obj.get("job_id", "")),
        "issue_id": str(item_obj.get("issue_id", "")),
        "created_utc": str(item_obj.get("created_utc", "")),
        "deleted_count": _as_int(item_obj.get("deleted_count", 0), 0),
        "rules": normalized_rules,
        "summary_text": str(item_obj.get("summary_text", "")),
    }


def _first_detail_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_backend_mode_status(payload: object) -> dict[str, object]:
    payload_obj = _obj_dict(payload)
    if not payload_obj:
        return _empty_backend_mode_status()
    fallback_export_errors = _obj_list(payload_obj.get("fallback_export_errors"))
    fallback_error = ""
    if fallback_export_errors:
        fallback_error = str(fallback_export_errors[0] or "").strip()
    mode = str(payload_obj.get("mode", "") or "").strip()
    return {
        "mode": mode,
        "authoritative_backend": str(payload_obj.get("authoritative_backend", "") or "").strip(),
        "backend_session_id": str(payload_obj.get("backend_session_id", "") or "").strip(),
        "recovery_status": str(payload_obj.get("recovery_status", "not_run") or "not_run").strip()
        or "not_run",
        "recovery_action": str(payload_obj.get("recovery_action", "") or "").strip(),
        "recovery_detail": _first_detail_text(
            payload_obj.get("recovery_detail"),
            payload_obj.get("main_db_validation"),
            payload_obj.get("backup_restore_error"),
            fallback_error,
            payload_obj.get("fallback_export_source"),
        ),
        "degraded": mode == "file_emergency"
        if "degraded" not in payload_obj
        else bool(payload_obj.get("degraded")),
    }


def build_backend_mode_status_payload(
    *,
    mode: object,
    authoritative_backend: object,
    backend_session_id: object,
    recovery: object,
) -> dict[str, object]:
    recovery_payload = _obj_dict(recovery)
    fallback_export_errors = _obj_list(recovery_payload.get("fallback_export_errors"))
    fallback_error = ""
    if fallback_export_errors:
        fallback_error = str(fallback_export_errors[0] or "").strip()
    return _normalize_backend_mode_status(
        {
            "mode": str(mode or ""),
            "authoritative_backend": str(authoritative_backend or ""),
            "backend_session_id": str(backend_session_id or ""),
            "recovery_status": str(recovery_payload.get("status") or "not_run"),
            "recovery_action": str(recovery_payload.get("recovery_action") or ""),
            "recovery_detail": _first_detail_text(
                recovery_payload.get("main_db_validation"),
                recovery_payload.get("backup_restore_error"),
                fallback_error,
                recovery_payload.get("fallback_export_source"),
            ),
        }
    )


def _normalize_operator_info(payload: object) -> dict[str, object]:
    payload_obj = _obj_dict(payload)
    if not payload_obj:
        return _empty_operator_info()
    items: list[dict[str, object]] = []
    for raw_item in _obj_list(payload_obj.get("cleanup_recent_status")):
        item = _normalize_cleanup_item(raw_item)
        if item is not None:
            items.append(item)
    return {
        "cleanup_recent_status": items,
        "backend_mode_status": _normalize_backend_mode_status(
            payload_obj.get("backend_mode_status")
        ),
    }


def _cleanup_item_fingerprint(item: dict[str, object]) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _merge_cleanup_items(*item_lists: list[object]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for item_list in item_lists:
        for raw_item in item_list:
            item = _normalize_cleanup_item(raw_item)
            if item is None:
                continue
            fingerprint = _cleanup_item_fingerprint(item)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            out.append(item)
    return out


def _runtime_payload(patches_root: Path) -> dict[str, object] | None:
    payload = _RUNTIME_OPERATOR_INFO.get(_runtime_key(patches_root))
    if payload is None:
        return None
    return _normalize_operator_info(payload)


def store_runtime_operator_info(
    patches_root: Path,
    payload: dict[str, object],
) -> dict[str, object]:
    normalized = _normalize_operator_info(payload)
    current = _runtime_payload(patches_root) or _empty_operator_info()
    current_obj = _obj_dict(current)
    payload_obj = _obj_dict(payload)
    merged_cleanup: list[dict[str, object]] = []
    for raw in _obj_list(current_obj.get("cleanup_recent_status")):
        item = _normalize_cleanup_item(raw)
        if item is not None:
            merged_cleanup.append(item)
    merged_backend = _normalize_backend_mode_status(current_obj.get("backend_mode_status"))
    normalized_obj = _obj_dict(normalized)
    if "cleanup_recent_status" in payload_obj:
        merged_cleanup = []
        for raw in _obj_list(normalized_obj.get("cleanup_recent_status")):
            item = _normalize_cleanup_item(raw)
            if item is not None:
                merged_cleanup.append(item)
    if "backend_mode_status" in payload_obj:
        merged_backend = _normalize_backend_mode_status(normalized_obj.get("backend_mode_status"))
    merged: dict[str, object] = {
        "cleanup_recent_status": merged_cleanup,
        "backend_mode_status": merged_backend,
    }
    _RUNTIME_OPERATOR_INFO[_runtime_key(patches_root)] = merged
    return merged


def append_cleanup_recent_status_runtime(
    patches_root: Path,
    cleanup_summary: dict[str, object],
) -> dict[str, object]:
    operator_info = load_operator_info(patches_root)
    cleanup_recent_status: list[dict[str, object]] = []
    for raw in _obj_list(operator_info.get("cleanup_recent_status")):
        item = _normalize_cleanup_item(raw)
        if item is not None:
            cleanup_recent_status.append(item)
    normalized = _normalize_cleanup_item(cleanup_summary)
    if normalized is not None:
        cleanup_recent_status.append(normalized)
    return store_runtime_operator_info(
        patches_root,
        {"cleanup_recent_status": cleanup_recent_status},
    )


def load_operator_info(patches_root: Path) -> dict[str, object]:
    path = operator_info_runtime_path(patches_root)
    file_payload = _empty_operator_info()
    if path.is_file():
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            file_payload = _empty_operator_info()
        else:
            file_payload = _normalize_operator_info(payload)
    runtime_payload = _runtime_payload(patches_root)
    if runtime_payload is None:
        return file_payload
    return {
        "cleanup_recent_status": _merge_cleanup_items(
            _obj_list(file_payload.get("cleanup_recent_status")),
            _obj_list(runtime_payload.get("cleanup_recent_status")),
        ),
        "backend_mode_status": _normalize_backend_mode_status(
            runtime_payload.get("backend_mode_status")
            or file_payload.get("backend_mode_status")
            or _empty_backend_mode_status()
        ),
    }


def write_operator_info(patches_root: Path, payload: dict[str, object]) -> dict[str, object]:
    path = operator_info_runtime_path(patches_root)
    normalized = _normalize_operator_info(payload)
    text = json.dumps(normalized, ensure_ascii=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)
    return store_runtime_operator_info(patches_root, normalized)


def append_cleanup_recent_status(
    patches_root: Path,
    cleanup_summary: dict[str, object],
) -> dict[str, object]:
    operator_info = load_operator_info(patches_root)
    cleanup_recent_status: list[dict[str, object]] = []
    for raw in _obj_list(operator_info.get("cleanup_recent_status")):
        item = _normalize_cleanup_item(raw)
        if item is not None:
            cleanup_recent_status.append(item)
    normalized = _normalize_cleanup_item(cleanup_summary)
    if normalized is not None:
        cleanup_recent_status.append(normalized)
    return write_operator_info(
        patches_root,
        {"cleanup_recent_status": cleanup_recent_status},
    )


def build_operator_info_sig(operator_info: dict[str, object]) -> str:
    payload = json.dumps(
        _normalize_operator_info(operator_info),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "operator_info:" + sha1(payload).hexdigest()
