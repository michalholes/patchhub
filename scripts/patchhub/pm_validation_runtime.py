from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    ZipTargetConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
    read_target_repo_from_zip_path,
)
from .zip_patch_subset import resolve_patch_zip_path

_STATUS_PASS = "pass"
_STATUS_FAIL = "fail"
_STATUS_ERROR = "error"
_STATUS_MISSING_CONTEXT = "missing_context"


def _validator_script_path(repo_root: Path) -> Path:
    return (repo_root / "governance" / "pm_validator.py").resolve()


def _instructions_zip_path(patches_root: Path, issue_id: str) -> Path | None:
    clean_issue = str(issue_id or "").strip()
    if not clean_issue.isdigit():
        return None
    root = patches_root.resolve()
    candidate = (patches_root / f"instructions_issue{clean_issue}.zip").resolve()
    if candidate.parent != root:
        return None
    return candidate


def _append_authority_source(authority_sources: list[str], path: Path) -> list[str]:
    path_text = str(path)
    if path_text in authority_sources:
        return list(authority_sources)
    return [*authority_sources, path_text]


def _zip_commit_cfg(cfg: Any) -> ZipCommitConfig:
    autofill = getattr(cfg, "autofill", object())
    return ZipCommitConfig(
        enabled=bool(getattr(autofill, "zip_commit_enabled", True)),
        filename=str(getattr(autofill, "zip_commit_filename", "COMMIT_MESSAGE.txt")),
        max_bytes=int(getattr(autofill, "zip_commit_max_bytes", 4096)),
        max_ratio=int(getattr(autofill, "zip_commit_max_ratio", 200)),
    )


def _zip_issue_cfg(cfg: Any) -> ZipIssueConfig:
    autofill = getattr(cfg, "autofill", object())
    return ZipIssueConfig(
        enabled=bool(getattr(autofill, "zip_issue_enabled", True)),
        filename=str(getattr(autofill, "zip_issue_filename", "ISSUE_NUMBER.txt")),
        max_bytes=int(getattr(autofill, "zip_issue_max_bytes", 128)),
        max_ratio=int(getattr(autofill, "zip_issue_max_ratio", 200)),
    )


def _zip_target_cfg() -> ZipTargetConfig:
    return ZipTargetConfig(
        enabled=True,
        filename="target.txt",
        max_bytes=128,
        max_ratio=200,
    )


def _derive_validation_inputs(self: Any, zpath: Path) -> tuple[str, str]:
    issue_id, _issue_err = read_issue_number_from_zip_path(zpath, _zip_issue_cfg(self.cfg))
    commit_message, _commit_err = read_commit_message_from_zip_path(
        zpath,
        _zip_commit_cfg(self.cfg),
    )
    if hasattr(self, "_derive_from_filename"):
        derived_issue, derived_commit = self._derive_from_filename(zpath.name)
    else:
        derived_issue, derived_commit = None, None
    return str(issue_id or derived_issue or ""), str(commit_message or derived_commit or "")


def _latest_file_by_pattern(root: Path, pattern: str) -> Path | None:
    best: Path | None = None
    best_key = (-1, "")
    for candidate in root.glob(pattern):
        if not candidate.is_file():
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        key = (int(getattr(stat, "st_mtime_ns", 0)), candidate.name)
        if key > best_key:
            best = candidate
            best_key = key
    return best


def _read_zip_target(path: Path) -> tuple[str | None, str | None]:
    return read_target_repo_from_zip_path(path, _zip_target_cfg())


def _latest_local_baseline_snapshot(patches_root: Path, target: str) -> Path | None:
    clean_target = str(target or "").strip()
    if not clean_target or not patches_root.exists():
        return None
    best: Path | None = None
    best_key = (-1, "")
    prefix = f"{clean_target}-main_"
    for candidate in patches_root.iterdir():
        if not candidate.is_file():
            continue
        if not candidate.name.startswith(prefix) or candidate.suffix != ".zip":
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        rel = candidate.relative_to(patches_root).as_posix()
        key = (int(getattr(stat, "st_mtime_ns", 0)), rel)
        if key > best_key:
            best = candidate
            best_key = key
    return None if best is None else best.resolve()


def _latest_repair_overlay(patches_root: Path, issue_id: str) -> Path | None:
    clean_issue = str(issue_id or "").strip()
    if not clean_issue.isdigit():
        return None
    return _latest_file_by_pattern(patches_root, f"patched_issue{clean_issue}_*.zip")


def _raw_output(stdout: str, stderr: str) -> str:
    out = str(stdout or "")
    err = str(stderr or "")
    if out and err:
        return out.rstrip("\n") + "\n\n[stderr]\n" + err
    if err:
        return "[stderr]\n" + err
    return out


def _parse_status(returncode: int, raw_output: str) -> str:
    if returncode == 0 and "RESULT: PASS" in raw_output:
        return _STATUS_PASS
    if any(
        token in raw_output
        for token in (
            "workspace_snapshot_required_for_initial_mode",
            "repair_overlay_not_found",
            "supplemental_requires_workspace_snapshot",
        )
    ):
        return _STATUS_MISSING_CONTEXT
    if (
        "RULE INSTRUCTIONS_EXTENSION: FAIL - instructions_zip_not_found" in raw_output
        or "RULE INSTRUCTIONS_LAYOUT: FAIL - missing_instructions_zip" in raw_output
    ):
        return _STATUS_MISSING_CONTEXT
    return _STATUS_FAIL


def _run_validator(
    *,
    repo_root: Path,
    issue_id: str,
    commit_message: str,
    patch_zip: Path,
    instructions_zip: Path,
    workspace_snapshot: Path | None,
    repair_overlay: Path | None,
    supplemental_files: list[str],
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_validator_script_path(repo_root)),
        str(issue_id),
        str(commit_message),
        str(patch_zip),
        str(instructions_zip),
    ]
    if workspace_snapshot is not None:
        cmd.extend(["--workspace-snapshot", str(workspace_snapshot)])
    if repair_overlay is not None:
        cmd.extend(["--repair-overlay", str(repair_overlay)])
    for item in supplemental_files:
        cmd.extend(["--supplemental-file", str(item)])
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_repair_requires_supplemental(raw_output: str) -> list[str]:
    marker = "repair_requires_supplemental_file:"
    for line in str(raw_output or "").splitlines():
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            parsed = ast.literal_eval(payload)
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        out: list[str] = []
        for item in parsed:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    return []


def _missing_context_payload(
    *,
    effective_mode: str,
    issue_id: str,
    commit_message: str,
    patch_path: str,
    authority_sources: list[str],
    supplemental_files: list[str],
    raw_output: str,
) -> dict[str, Any]:
    return {
        "status": _STATUS_MISSING_CONTEXT,
        "effective_mode": effective_mode,
        "issue_id": issue_id,
        "commit_message": commit_message,
        "patch_path": patch_path,
        "authority_sources": authority_sources,
        "supplemental_files": supplemental_files,
        "raw_output": raw_output,
    }


def build_patch_zip_pm_validation(self: Any, patch_path: str) -> dict[str, Any]:
    patch_rel, patch_zip = resolve_patch_zip_path(
        jail=self.jail,
        patches_root_rel=self.cfg.paths.patches_root,
        patch_path=str(patch_path or ""),
    )
    issue_id, commit_message = _derive_validation_inputs(self, patch_zip)
    zip_issue_id, zip_issue_err = read_issue_number_from_zip_path(
        patch_zip,
        _zip_issue_cfg(self.cfg),
    )
    if zip_issue_id is None or not zip_issue_id.isdigit():
        return _missing_context_payload(
            effective_mode="initial",
            issue_id=issue_id,
            commit_message=commit_message,
            patch_path=patch_rel,
            authority_sources=[],
            supplemental_files=[],
            raw_output=f"zip_issue_missing_or_invalid:{zip_issue_err or 'unknown'}",
        )
    instructions_zip = _instructions_zip_path(self.patches_root, zip_issue_id)
    if instructions_zip is None:
        return _missing_context_payload(
            effective_mode="initial",
            issue_id=issue_id,
            commit_message=commit_message,
            patch_path=patch_rel,
            authority_sources=[],
            supplemental_files=[],
            raw_output=(f"instructions_zip_invalid:instructions_issue{zip_issue_id}.zip"),
        )
    overlay_path = _latest_repair_overlay(self.patches_root, zip_issue_id)
    effective_mode = "repair-overlay-only" if overlay_path is not None else "initial"
    authority_sources: list[str] = []
    passed_sources: list[str] = []
    supplemental_files: list[str] = []
    workspace_snapshot: Path | None = None

    if overlay_path is not None:
        authority_sources.append(str(overlay_path))
    else:
        initial_target, initial_target_err = _read_zip_target(patch_zip)
        if initial_target is None:
            return _missing_context_payload(
                effective_mode=effective_mode,
                issue_id=issue_id,
                commit_message=commit_message,
                patch_path=patch_rel,
                authority_sources=authority_sources,
                supplemental_files=supplemental_files,
                raw_output=(f"zip_target_missing_or_invalid:{initial_target_err or 'unknown'}"),
            )
        workspace_snapshot = _latest_local_baseline_snapshot(
            self.patches_root,
            initial_target,
        )
        if workspace_snapshot is not None:
            authority_sources.append(str(workspace_snapshot))

    proc = _run_validator(
        repo_root=self.repo_root,
        issue_id=issue_id,
        commit_message=commit_message,
        patch_zip=patch_zip,
        instructions_zip=instructions_zip,
        workspace_snapshot=workspace_snapshot,
        repair_overlay=overlay_path,
        supplemental_files=[],
    )
    passed_sources = _append_authority_source(authority_sources, instructions_zip)
    raw = _raw_output(proc.stdout, proc.stderr)

    if overlay_path is not None:
        supplemental_files = _parse_repair_requires_supplemental(raw)
        if supplemental_files:
            repair_target, repair_target_err = _read_zip_target(overlay_path)
            if repair_target is None:
                return _missing_context_payload(
                    effective_mode=effective_mode,
                    issue_id=issue_id,
                    commit_message=commit_message,
                    patch_path=patch_rel,
                    authority_sources=passed_sources,
                    supplemental_files=supplemental_files,
                    raw_output=(
                        raw.rstrip("\n")
                        + "\n\n[repair supplemental missing context]\n"
                        + "zip_target_missing_or_invalid:"
                        + f"{repair_target_err or 'unknown'}"
                    ),
                )
            workspace_snapshot = _latest_local_baseline_snapshot(
                self.patches_root,
                repair_target,
            )
            if workspace_snapshot is None:
                proc = _run_validator(
                    repo_root=self.repo_root,
                    issue_id=issue_id,
                    commit_message=commit_message,
                    patch_zip=patch_zip,
                    instructions_zip=instructions_zip,
                    workspace_snapshot=None,
                    repair_overlay=overlay_path,
                    supplemental_files=supplemental_files,
                )
                rerun_raw = _raw_output(proc.stdout, proc.stderr)
                return _missing_context_payload(
                    effective_mode=effective_mode,
                    issue_id=issue_id,
                    commit_message=commit_message,
                    patch_path=patch_rel,
                    authority_sources=passed_sources,
                    supplemental_files=supplemental_files,
                    raw_output=(
                        "[overlay-only]\n"
                        + raw.rstrip("\n")
                        + "\n\n[repair-supplemental]\n"
                        + rerun_raw
                    ),
                )
            authority_sources.append(str(workspace_snapshot))
            proc = _run_validator(
                repo_root=self.repo_root,
                issue_id=issue_id,
                commit_message=commit_message,
                patch_zip=patch_zip,
                instructions_zip=instructions_zip,
                workspace_snapshot=workspace_snapshot,
                repair_overlay=overlay_path,
                supplemental_files=supplemental_files,
            )
            rerun_raw = _raw_output(proc.stdout, proc.stderr)
            effective_mode = "repair-supplemental"
            passed_sources = _append_authority_source(authority_sources, instructions_zip)
            raw = "[overlay-only]\n" + raw.rstrip("\n") + "\n\n[repair-supplemental]\n" + rerun_raw

    return {
        "status": _parse_status(proc.returncode, raw),
        "effective_mode": effective_mode,
        "issue_id": issue_id,
        "commit_message": commit_message,
        "patch_path": patch_rel,
        "authority_sources": passed_sources,
        "supplemental_files": supplemental_files,
        "raw_output": raw,
    }


def pm_validation_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)
