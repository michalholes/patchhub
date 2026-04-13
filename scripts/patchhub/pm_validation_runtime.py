from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .governance_toolkit_runtime import (
    GovernanceToolkitRuntimeError,
    resolve_governance_toolkit,
)
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
_INSTRUCTIONS_BASENAME_RE = re.compile(r"^instructions_(?P<issue>\d+)_v(?P<version>[1-9]\d*)\.zip$")
_RULE_FAIL_RE = re.compile(
    r"^RULE (?P<rule>[A-Z0-9_:-]+): FAIL(?: - (?P<detail>.*))?$",
    re.MULTILINE,
)
_SUMMARY_TOOLKIT = "toolkit resolution"
_SUMMARY_INSTRUCTIONS = "missing or invalid instructions artifact"
_SUMMARY_ZIP_METADATA = "missing or invalid zip metadata"
_SUMMARY_GIT_APPLY = "git apply"
_SUMMARY_COMPILE_OR_SYNTAX = "compile or syntax"
_SUMMARY_MONOLITH = "monolith"
_SUMMARY_EXTERNAL_GATE = "external gate"
_SUMMARY_VALIDATION = "validation error"
_SUMMARY_GENERIC = "generic validator failure"


def _instructions_paths(patches_root: Path, issue_id: str) -> tuple[Path | None, Path | None]:
    clean_issue = str(issue_id or "").strip()
    if not clean_issue.isdigit():
        return None, None
    root = patches_root.resolve()
    best: Path | None = None
    best_version = -1
    try:
        candidates = list(root.iterdir())
    except OSError:
        candidates = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        match = _INSTRUCTIONS_BASENAME_RE.fullmatch(candidate.name)
        if match is None or match.group("issue") != clean_issue:
            continue
        version = int(match.group("version"))
        resolved = candidate.resolve()
        if resolved.parent != root:
            continue
        if version > best_version:
            best = resolved
            best_version = version
    placeholder = (patches_root / f"instructions_placeholder_{clean_issue}.zip").resolve()
    if placeholder.parent != root:
        return best, None
    return best, placeholder


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
    return _STATUS_FAIL


def _classify_validator_rule_failure(raw_output: str) -> str:
    for match in _RULE_FAIL_RE.finditer(str(raw_output or "")):
        rule_name = str(match.group("rule") or "").strip().lower().replace("_", " ")
        detail = str(match.group("detail") or "").strip().lower().replace("_", " ")
        haystack = f"{rule_name} {detail}".strip()
        if "instructions" in haystack:
            return _SUMMARY_INSTRUCTIONS
        if any(token in haystack for token in ("zip", "target", "commit", "issue", "metadata")):
            return _SUMMARY_ZIP_METADATA
        if "git apply" in haystack or ("apply" in haystack and "git" in haystack):
            return _SUMMARY_GIT_APPLY
        if any(token in haystack for token in ("compile", "syntax")):
            return _SUMMARY_COMPILE_OR_SYNTAX
        if "monolith" in haystack:
            return _SUMMARY_MONOLITH
        if "external gate" in haystack or "externalgate" in haystack:
            return _SUMMARY_EXTERNAL_GATE
        return _SUMMARY_VALIDATION
    if "RESULT: FAIL" in str(raw_output or ""):
        return _SUMMARY_GENERIC
    return ""


def _failure_summary(raw_output: str, toolkit_resolution: dict[str, Any] | None) -> str:
    resolution = dict(toolkit_resolution or {})
    resolution_error = str(resolution.get("error") or "").strip()
    if resolution_error:
        return _SUMMARY_TOOLKIT

    raw = str(raw_output or "").strip()
    if not raw:
        return ""

    if raw.startswith("instructions_placeholder_invalid:"):
        return _SUMMARY_INSTRUCTIONS
    if raw.startswith("toolkit_resolution_failed:"):
        return _SUMMARY_TOOLKIT
    if raw.startswith("zip_issue_missing_or_invalid:"):
        return _SUMMARY_ZIP_METADATA
    if raw.startswith("zip_target_missing_or_invalid:"):
        return _SUMMARY_ZIP_METADATA
    if raw.startswith("repair_target_missing_or_invalid:"):
        return _SUMMARY_ZIP_METADATA
    if raw.startswith("repair_workspace_snapshot_missing:"):
        return _SUMMARY_VALIDATION

    classified = _classify_validator_rule_failure(raw)
    return classified or _SUMMARY_GENERIC


def _run_validator(
    *,
    validator_script: Path,
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
        str(validator_script),
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
    cmd.append("--skip-external-gates")
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
    toolkit_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure_summary = _failure_summary(raw_output, toolkit_resolution)
    return {
        "status": _STATUS_FAIL,
        "effective_mode": effective_mode,
        "issue_id": issue_id,
        "commit_message": commit_message,
        "patch_path": patch_path,
        "authority_sources": authority_sources,
        "supplemental_files": supplemental_files,
        "failure_summary": failure_summary,
        "raw_output": raw_output,
        "toolkit_resolution": dict(toolkit_resolution or {}),
    }


def build_patch_zip_pm_validation(self: Any, patch_path: str) -> dict[str, Any]:
    patch_rel, patch_zip = resolve_patch_zip_path(
        jail=self.jail,
        patches_root_rel=self.cfg.paths.patches_root,
        patch_path=str(patch_path or ""),
    )
    issue_id, commit_message = _derive_validation_inputs(self, patch_zip)
    toolkit_resolution: dict[str, Any] = {}
    try:
        toolkit = resolve_governance_toolkit(self.cfg)
        toolkit_resolution = dict(toolkit.resolution)
    except GovernanceToolkitRuntimeError as exc:
        toolkit_resolution = dict(exc.resolution)
        raw_output = f"toolkit_resolution_failed:{exc}"
        return {
            "status": _STATUS_FAIL,
            "effective_mode": "initial",
            "issue_id": issue_id,
            "commit_message": commit_message,
            "patch_path": patch_rel,
            "authority_sources": [],
            "supplemental_files": [],
            "failure_summary": _failure_summary(raw_output, toolkit_resolution),
            "raw_output": raw_output,
            "toolkit_resolution": toolkit_resolution,
        }
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
            toolkit_resolution=toolkit_resolution,
        )
    instructions_authority, instructions_placeholder = _instructions_paths(
        self.patches_root,
        zip_issue_id,
    )
    if instructions_placeholder is None:
        return _missing_context_payload(
            effective_mode="initial",
            issue_id=issue_id,
            commit_message=commit_message,
            patch_path=patch_rel,
            authority_sources=[],
            supplemental_files=[],
            raw_output=f"instructions_placeholder_invalid:{zip_issue_id}",
            toolkit_resolution=toolkit_resolution,
        )
    instructions_zip = (
        instructions_authority if instructions_authority is not None else instructions_placeholder
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
                toolkit_resolution=toolkit_resolution,
            )
        workspace_snapshot = _latest_local_baseline_snapshot(
            self.patches_root,
            initial_target,
        )
        if workspace_snapshot is not None:
            authority_sources.append(str(workspace_snapshot))

    proc = _run_validator(
        validator_script=toolkit.pm_validator_path,
        repo_root=self.repo_root,
        issue_id=issue_id,
        commit_message=commit_message,
        patch_zip=patch_zip,
        instructions_zip=instructions_zip,
        workspace_snapshot=workspace_snapshot,
        repair_overlay=overlay_path,
        supplemental_files=[],
    )
    passed_sources = list(authority_sources)
    if instructions_authority is not None and str(instructions_authority) not in passed_sources:
        passed_sources.append(str(instructions_authority))
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
                    raw_output=f"repair_target_missing_or_invalid:{repair_target_err or 'unknown'}",
                    toolkit_resolution=toolkit_resolution,
                )
            workspace_snapshot = _latest_local_baseline_snapshot(
                self.patches_root,
                repair_target,
            )
            if workspace_snapshot is None:
                return _missing_context_payload(
                    effective_mode=effective_mode,
                    issue_id=issue_id,
                    commit_message=commit_message,
                    patch_path=patch_rel,
                    authority_sources=passed_sources,
                    supplemental_files=supplemental_files,
                    raw_output=f"repair_workspace_snapshot_missing:{repair_target}",
                    toolkit_resolution=toolkit_resolution,
                )
            if str(workspace_snapshot) not in authority_sources:
                authority_sources.append(str(workspace_snapshot))
            proc = _run_validator(
                validator_script=toolkit.pm_validator_path,
                repo_root=self.repo_root,
                issue_id=issue_id,
                commit_message=commit_message,
                patch_zip=patch_zip,
                instructions_zip=instructions_zip,
                workspace_snapshot=workspace_snapshot,
                repair_overlay=overlay_path,
                supplemental_files=supplemental_files,
            )
            effective_mode = "repair-supplemental"
            passed_sources = list(authority_sources)
            if (
                instructions_authority is not None
                and str(instructions_authority) not in passed_sources
            ):
                passed_sources.append(str(instructions_authority))
            raw = _raw_output(proc.stdout, proc.stderr)

    status = _parse_status(proc.returncode, raw)
    return {
        "status": status,
        "effective_mode": effective_mode,
        "issue_id": issue_id,
        "commit_message": commit_message,
        "patch_path": patch_rel,
        "authority_sources": passed_sources,
        "supplemental_files": supplemental_files,
        "failure_summary": ""
        if status == _STATUS_PASS
        else _failure_summary(raw, toolkit_resolution),
        "raw_output": raw,
        "toolkit_resolution": toolkit_resolution,
    }


def pm_validation_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)
