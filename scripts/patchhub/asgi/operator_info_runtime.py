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


def _empty_operator_info() -> dict[str, Any]:
    return {"cleanup_recent_status": []}


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
    return {"cleanup_recent_status": items}


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
    _RUNTIME_OPERATOR_INFO[_runtime_key(patches_root)] = normalized
    return normalized


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
        )
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
