from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import Any

_OPERATOR_INFO_RUNTIME_NAME = "patchhub_operator_info.json"
_RUNTIME_OPERATOR_INFO: dict[str, dict[str, Any]] = {}


def operator_info_runtime_path(patches_root: Path) -> Path:
    return patches_root / "artifacts" / _OPERATOR_INFO_RUNTIME_NAME


def _runtime_key(patches_root: Path) -> str:
    return str(patches_root)


def _empty_backend_mode_status() -> dict[str, Any]:
    return {
        "mode": "",
        "authoritative_backend": "",
        "backend_session_id": "",
        "recovery_status": "not_run",
        "recovery_action": "",
        "recovery_detail": "",
        "degraded": False,
    }


def _empty_operator_info() -> dict[str, Any]:
    return {
        "cleanup_recent_status": [],
        "backend_mode_status": _empty_backend_mode_status(),
    }


def _normalize_cleanup_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    rules = item.get("rules")
    normalized_rules: list[dict[str, Any]] = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            normalized_rules.append(
                {
                    "filename_pattern": str(rule.get("filename_pattern", "")),
                    "keep_count": int(rule.get("keep_count", 0) or 0),
                    "matched_count": int(rule.get("matched_count", 0) or 0),
                    "deleted_count": int(rule.get("deleted_count", 0) or 0),
                }
            )
    return {
        "job_id": str(item.get("job_id", "")),
        "issue_id": str(item.get("issue_id", "")),
        "created_utc": str(item.get("created_utc", "")),
        "deleted_count": int(item.get("deleted_count", 0) or 0),
        "rules": normalized_rules,
        "summary_text": str(item.get("summary_text", "")),
    }


def _first_detail_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_backend_mode_status(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_backend_mode_status()
    fallback_export_errors = payload.get("fallback_export_errors")
    fallback_error = ""
    if isinstance(fallback_export_errors, list) and fallback_export_errors:
        fallback_error = str(fallback_export_errors[0] or "").strip()
    mode = str(payload.get("mode", "") or "").strip()
    return {
        "mode": mode,
        "authoritative_backend": str(payload.get("authoritative_backend", "") or "").strip(),
        "backend_session_id": str(payload.get("backend_session_id", "") or "").strip(),
        "recovery_status": str(payload.get("recovery_status", "not_run") or "not_run").strip()
        or "not_run",
        "recovery_action": str(payload.get("recovery_action", "") or "").strip(),
        "recovery_detail": _first_detail_text(
            payload.get("recovery_detail"),
            payload.get("main_db_validation"),
            payload.get("backup_restore_error"),
            fallback_error,
            payload.get("fallback_export_source"),
        ),
        "degraded": (
            mode == "file_emergency" if "degraded" not in payload else bool(payload.get("degraded"))
        ),
    }


def build_backend_mode_status_payload(
    *,
    mode: Any,
    authoritative_backend: Any,
    backend_session_id: Any,
    recovery: Any,
) -> dict[str, Any]:
    recovery_payload = recovery if isinstance(recovery, dict) else {}
    fallback_export_errors = recovery_payload.get("fallback_export_errors")
    fallback_error = ""
    if isinstance(fallback_export_errors, list) and fallback_export_errors:
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


def _normalize_operator_info(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_operator_info()
    raw_items = payload.get("cleanup_recent_status")
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            item = _normalize_cleanup_item(raw_item)
            if item is not None:
                items.append(item)
    return {
        "cleanup_recent_status": items,
        "backend_mode_status": _normalize_backend_mode_status(payload.get("backend_mode_status")),
    }


def _cleanup_item_fingerprint(item: dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _merge_cleanup_items(*item_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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


def _runtime_payload(patches_root: Path) -> dict[str, Any] | None:
    payload = _RUNTIME_OPERATOR_INFO.get(_runtime_key(patches_root))
    if payload is None:
        return None
    return _normalize_operator_info(payload)


def store_runtime_operator_info(
    patches_root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_operator_info(payload)
    current = _runtime_payload(patches_root) or _empty_operator_info()
    merged = {
        "cleanup_recent_status": list(current.get("cleanup_recent_status") or []),
        "backend_mode_status": dict(
            current.get("backend_mode_status") or _empty_backend_mode_status()
        ),
    }
    if isinstance(payload, dict) and "cleanup_recent_status" in payload:
        merged["cleanup_recent_status"] = list(normalized["cleanup_recent_status"])
    if isinstance(payload, dict) and "backend_mode_status" in payload:
        merged["backend_mode_status"] = dict(normalized["backend_mode_status"])
    _RUNTIME_OPERATOR_INFO[_runtime_key(patches_root)] = merged
    return merged


def append_cleanup_recent_status_runtime(
    patches_root: Path,
    cleanup_summary: dict[str, Any],
) -> dict[str, Any]:
    operator_info = load_operator_info(patches_root)
    cleanup_recent_status = list(operator_info.get("cleanup_recent_status") or [])
    normalized = _normalize_cleanup_item(cleanup_summary)
    if normalized is not None:
        cleanup_recent_status.append(normalized)
    return store_runtime_operator_info(
        patches_root,
        {"cleanup_recent_status": cleanup_recent_status},
    )


def load_operator_info(patches_root: Path) -> dict[str, Any]:
    path = operator_info_runtime_path(patches_root)
    file_payload = _empty_operator_info()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            file_payload = _empty_operator_info()
        else:
            file_payload = _normalize_operator_info(payload)
    runtime_payload = _runtime_payload(patches_root)
    if runtime_payload is None:
        return file_payload
    return {
        "cleanup_recent_status": _merge_cleanup_items(
            list(file_payload.get("cleanup_recent_status") or []),
            list(runtime_payload.get("cleanup_recent_status") or []),
        ),
        "backend_mode_status": dict(
            runtime_payload.get("backend_mode_status")
            or file_payload.get("backend_mode_status")
            or _empty_backend_mode_status()
        ),
    }


def write_operator_info(patches_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
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
    cleanup_summary: dict[str, Any],
) -> dict[str, Any]:
    operator_info = load_operator_info(patches_root)
    cleanup_recent_status = list(operator_info.get("cleanup_recent_status") or [])
    normalized = _normalize_cleanup_item(cleanup_summary)
    if normalized is not None:
        cleanup_recent_status.append(normalized)
    return write_operator_info(
        patches_root,
        {"cleanup_recent_status": cleanup_recent_status},
    )


def build_operator_info_sig(operator_info: dict[str, Any]) -> str:
    payload = json.dumps(
        _normalize_operator_info(operator_info),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "operator_info:" + sha1(payload).hexdigest()
