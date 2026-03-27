from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

_MANIFEST_BASENAME = "rollback_scope_manifest.json"


class RollbackManifestError(RuntimeError):
    pass


class RollbackSelectionError(RuntimeError):
    pass


def manifest_rel_path_for_job(job_id: str) -> str:
    text = str(job_id or "").strip()
    if not text:
        raise RollbackManifestError("missing source job id for rollback manifest path")
    return f"{text}/{_MANIFEST_BASENAME}"


def build_manifest_for_job(
    *,
    repo_root: Path,
    source_job_id: str,
    issue_id: str,
    selected_target_repo_token: str,
    effective_runner_target_repo: str,
    run_start_sha: str,
    run_end_sha: str,
    authority_kind: str,
    authority_source_ref: str,
) -> dict[str, Any]:
    entries = _diff_entries(
        repo_root=repo_root,
        run_start_sha=run_start_sha,
        run_end_sha=run_end_sha,
    )
    return {
        "version": 1,
        "source_job_id": str(source_job_id or ""),
        "issue_id": str(issue_id or ""),
        "selected_target_repo_token": str(selected_target_repo_token or ""),
        "effective_runner_target_repo": str(effective_runner_target_repo or ""),
        "rollback_authority_kind": str(authority_kind or ""),
        "rollback_authority_source_ref": str(authority_source_ref or ""),
        "entries": entries,
    }


def write_manifest(job_dir: Path, manifest: dict[str, Any]) -> tuple[str, str]:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / _MANIFEST_BASENAME
    data = json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    path.write_text(data, encoding="utf-8")
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return manifest_rel_path_for_job(job_dir.name), digest


def load_manifest(jobs_root: Path, rel_path: str, expected_hash: str | None) -> dict[str, Any]:
    rel = str(rel_path or "").strip()
    if not rel:
        raise RollbackManifestError("missing rollback manifest path")
    path = (Path(jobs_root) / rel).resolve()
    try:
        path.relative_to(Path(jobs_root).resolve())
    except Exception as exc:
        raise RollbackManifestError("rollback manifest path escapes jobs_root") from exc
    if not path.is_file():
        raise RollbackManifestError("rollback manifest file is missing")
    data = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    wanted = str(expected_hash or "").strip()
    if wanted and digest != wanted:
        raise RollbackManifestError("rollback manifest hash mismatch")
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise RollbackManifestError("rollback manifest must be a JSON object")
    return parsed


def normalize_selected_entries(
    manifest: dict[str, Any],
    *,
    scope_kind: str,
    selected_repo_paths: list[str] | None,
) -> dict[str, Any]:
    entries = _manifest_entries(manifest)
    kind = str(scope_kind or "").strip()
    if kind not in {"full", "subset"}:
        raise RollbackSelectionError("rollback_scope_kind must be full or subset")
    if kind == "full":
        selected = entries
    else:
        raw_selected = _normalize_path_list(selected_repo_paths or [])
        if not raw_selected:
            raise RollbackSelectionError(
                "rollback_selected_repo_paths is required for subset rollback"
            )
        by_path: dict[str, dict[str, Any]] = {}
        for entry_item in entries:
            for path in list(entry_item.get("selection_paths") or []):
                by_path[str(path)] = entry_item
        seen_ids: set[str] = set()
        selected = []
        for path in raw_selected:
            matched_entry = by_path.get(path)
            if matched_entry is None:
                raise RollbackSelectionError(
                    "selected rollback path does not resolve to authority entry"
                )
            entry_id = str(matched_entry.get("entry_id") or "")
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            selected.append(matched_entry)
    selected_ids = [str(item.get("entry_id") or "") for item in selected]
    selected_paths = sorted(
        {
            str(path)
            for item in selected
            for path in list(item.get("selection_paths") or [])
            if str(path)
        }
    )
    restore_paths = sorted(
        {
            str(path)
            for item in selected
            for path in list(item.get("restore_paths") or [])
            if str(path)
        }
    )
    return {
        "scope_kind": kind,
        "entries": selected,
        "selected_entry_ids": selected_ids,
        "selected_repo_paths": selected_paths,
        "restore_paths": restore_paths,
    }


def entry_display_label(entry: dict[str, Any]) -> str:
    lifecycle = str(entry.get("lifecycle_kind") or "")
    old_path = str(entry.get("old_path") or "")
    new_path = str(entry.get("new_path") or "")
    if lifecycle == "rename":
        return f"rename {old_path} -> {new_path}"
    if lifecycle == "delete":
        return f"delete {old_path}"
    if lifecycle == "add":
        return f"add {new_path}"
    if lifecycle == "modify":
        return f"modify {new_path}"
    return new_path or old_path or lifecycle


def _normalize_path_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise RollbackManifestError("rollback manifest entries must be a JSON array")
    out: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise RollbackManifestError("rollback manifest entry must be an object")
        out.append(raw)
    return out


def _diff_entries(
    *,
    repo_root: Path,
    run_start_sha: str,
    run_end_sha: str,
) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-M",
            str(run_start_sha or ""),
            str(run_end_sha or ""),
        ],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RollbackManifestError(_git_error("cannot build rollback manifest", result))
    entries: list[dict[str, Any]] = []
    for idx, raw in enumerate(str(result.stdout or "").splitlines(), start=1):
        line = str(raw or "").strip()
        if not line:
            continue
        parts = line.split("\t")
        status = str(parts[0] or "")
        if status.startswith("R") and len(parts) >= 3:
            old_path = str(parts[1] or "").strip()
            new_path = str(parts[2] or "").strip()
            entries.append(
                {
                    "entry_id": f"entry_{idx}",
                    "lifecycle_kind": "rename",
                    "old_path": old_path,
                    "new_path": new_path,
                    "selection_paths": [old_path, new_path],
                    "restore_paths": [old_path, new_path],
                    "source_descriptor": {
                        "kind": "git_path_pair",
                        "run_start_sha": str(run_start_sha or ""),
                        "run_end_sha": str(run_end_sha or ""),
                    },
                }
            )
            continue
        if len(parts) < 2:
            raise RollbackManifestError("unsupported git diff name-status output")
        path = str(parts[1] or "").strip()
        lifecycle = _single_path_lifecycle(status)
        old_path = path if lifecycle in {"modify", "delete"} else ""
        new_path = path if lifecycle in {"modify", "add"} else ""
        entries.append(
            {
                "entry_id": f"entry_{idx}",
                "lifecycle_kind": lifecycle,
                "old_path": old_path,
                "new_path": new_path,
                "selection_paths": [path],
                "restore_paths": [path],
                "source_descriptor": {
                    "kind": "git_path",
                    "run_start_sha": str(run_start_sha or ""),
                    "run_end_sha": str(run_end_sha or ""),
                },
            }
        )
    return entries


def _single_path_lifecycle(status: str) -> str:
    text = str(status or "").strip().upper()
    if text == "A":
        return "add"
    if text == "M":
        return "modify"
    if text == "D":
        return "delete"
    raise RollbackManifestError(f"unsupported rollback lifecycle status: {text}")


def _git_error(prefix: str, result: subprocess.CompletedProcess[str]) -> str:
    parts = [str(prefix or "git command failed"), f"rc={int(result.returncode)}"]
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    return "; ".join(parts)
