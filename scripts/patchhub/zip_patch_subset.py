from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

_PATCH_ENTRY_PREFIX = "patches/per_file/"
_PATCH_SUFFIX = ".patch"
_ROOT_METADATA_NAMES = ("COMMIT_MESSAGE.txt", "ISSUE_NUMBER.txt", "target.txt")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_patch_rel_path(*, patches_root_rel: str, patch_path: str) -> str:
    rel = str(patch_path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("Missing patch_path")
    prefix = str(patches_root_rel or "patches").rstrip("/")
    if rel == prefix:
        return ""
    if rel.startswith(prefix + "/"):
        return rel[len(prefix) + 1 :]
    return rel


def resolve_patch_zip_path(
    *,
    jail: Any,
    patches_root_rel: str,
    patch_path: str,
) -> tuple[str, Path]:
    rel = normalize_patch_rel_path(patches_root_rel=patches_root_rel, patch_path=patch_path)
    zpath = jail.resolve_rel(rel)
    if not zpath.exists() or not zpath.is_file():
        raise ValueError("Patch zip not found")
    if zpath.suffix.lower() != ".zip":
        raise ValueError("Patch path is not a .zip file")
    return rel, zpath


def _repo_path_from_patch_member(name: str) -> str | None:
    if not name.startswith(_PATCH_ENTRY_PREFIX):
        return None
    if not name.endswith(_PATCH_SUFFIX):
        return None
    encoded = name[len(_PATCH_ENTRY_PREFIX) : -len(_PATCH_SUFFIX)]
    if not encoded:
        return None
    if "/" in encoded or "\\" in encoded:
        return None
    repo_path = encoded.replace("__", "/")
    if not repo_path or repo_path.startswith("/"):
        return None
    parts = Path(repo_path).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    return repo_path


def build_zip_patch_manifest(*, patch_path: str, zpath: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zpath, "r") as zf:
        names = sorted(zf.namelist())

    entries: list[dict[str, Any]] = []
    root_metadata_present: list[str] = []
    for name in names:
        if name in _ROOT_METADATA_NAMES:
            root_metadata_present.append(name)
            continue
        if not name.endswith(_PATCH_SUFFIX):
            continue
        repo_path = _repo_path_from_patch_member(name)
        entries.append(
            {
                "zip_member": name,
                "repo_path": repo_path,
                "selectable": repo_path is not None,
            }
        )

    selectable = bool(entries) and all(bool(item.get("selectable")) for item in entries)
    if not entries:
        reason = "zip_has_no_patch_entries"
    elif not selectable:
        reason = "zip_not_pm_per_file_layout"
    else:
        reason = "ok"

    return {
        "path": str(patch_path),
        "is_zip": True,
        "selectable": selectable,
        "reason": reason,
        "patch_entry_count": len(entries),
        "entries": entries,
        "root_metadata_present": sorted(root_metadata_present),
    }


def selected_repo_paths_from_manifest(
    manifest: dict[str, Any],
    selected_patch_entries: list[str],
) -> list[str]:
    selected = list(selected_patch_entries)
    allowed = {
        str(item.get("zip_member", "")): str(item.get("repo_path", ""))
        for item in list(manifest.get("entries") or [])
        if item.get("selectable") and item.get("repo_path")
    }
    repo_paths: list[str] = []
    for name in selected:
        repo_path = allowed.get(str(name))
        if repo_path:
            repo_paths.append(repo_path)
    return repo_paths


def validate_selected_patch_entries(
    manifest: dict[str, Any],
    selected_patch_entries: list[str],
) -> list[str]:
    if not manifest.get("selectable"):
        raise ValueError("Zip subset selection is not available for this patch")

    allowed = {
        str(item.get("zip_member", ""))
        for item in list(manifest.get("entries") or [])
        if item.get("selectable")
    }
    if not allowed:
        raise ValueError("Zip subset selection is not available for this patch")

    selected: list[str] = []
    seen: set[str] = set()
    for raw in list(selected_patch_entries or []):
        name = str(raw or "")
        if not name or name in seen:
            continue
        if name not in allowed:
            raise ValueError("selected_patch_entries contains an unknown zip member")
        selected.append(name)
        seen.add(name)

    if not selected:
        raise ValueError("selected_patch_entries is empty")

    selected.sort()
    return selected


def derive_subset_patch_rel_path(*, original_patch_path: str, job_id: str) -> str:
    base = Path(str(original_patch_path or "patch.zip").replace("\\", "/")).name
    stem = base[:-4] if base.lower().endswith(".zip") else base
    safe_stem = _SAFE_NAME_RE.sub("_", stem).strip("._-") or "patch"
    safe_job = _SAFE_NAME_RE.sub("_", str(job_id or "job")).strip("._-") or "job"
    return f"{safe_stem}__subset__{safe_job}.zip"


def create_subset_zip(
    *,
    source_zip: Path,
    dest_zip: Path,
    selected_patch_entries: list[str],
) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(source_zip, "r") as src,
        zipfile.ZipFile(
            dest_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as dst,
    ):
        for meta_name in _ROOT_METADATA_NAMES:
            try:
                data = src.read(meta_name)
            except KeyError:
                continue
            dst.writestr(meta_name, data)
        for name in selected_patch_entries:
            dst.writestr(name, src.read(name))
