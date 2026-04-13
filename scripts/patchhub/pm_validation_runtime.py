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
_RULE_RESULT_RE = re.compile(
    (
        r"^RULE (?P<rule>[A-Z0-9_.:-]+): "
        r"(?P<status>FAIL|MANUAL_REVIEW_REQUIRED)(?: - (?P<detail>.*))?$"
    ),
    re.MULTILINE,
)
_SUMMARY_TOOLKIT = "toolkit resolution"
_SUMMARY_INSTRUCTIONS_EXTENSION = "instructions extension"
_SUMMARY_INSTRUCTIONS_LAYOUT = "instructions layout"
_SUMMARY_INSTRUCTIONS_HANDOFF = "instructions handoff"
_SUMMARY_PACK_JSON = "constraint pack json"
_SUMMARY_PACK_HASH_FILE = "constraint pack hash file"
_SUMMARY_PACK_HASH_INTEGRITY = "constraint pack hash integrity"
_SUMMARY_PACK_RECOMPUTE = "constraint pack recompute"
_SUMMARY_PACK_WIRING = "constraint pack wiring"
_SUMMARY_PACK_FORBIDDEN_BYPASS = "constraint pack forbidden bypass"
_SUMMARY_PACK_DOWNSTREAM_COVERAGE = "constraint pack downstream coverage"
_SUMMARY_PACK_REQUIRED_VALIDATION = "constraint pack required validation"
_SUMMARY_PACK_SCOPE_MAPPING = "constraint pack scope mapping"
_SUMMARY_PACK_VERDICT_COVERAGE = "constraint pack verdict coverage"
_SUMMARY_PACK_RULE = "constraint pack rule"
_SUMMARY_PATCH_EXTENSION = "patch extension"
_SUMMARY_PATCH_BASENAME = "patch basename"
_SUMMARY_COMMIT_MESSAGE_FILE = "commit message file"
_SUMMARY_ISSUE_NUMBER_FILE = "issue number file"
_SUMMARY_TARGET_FILE = "target file"
_SUMMARY_INITIAL_TARGET_SOURCE = "initial target source"
_SUMMARY_INITIAL_TARGET_MATCH = "initial target match"
_SUMMARY_REPAIR_TARGET_SOURCE = "repair target source"
_SUMMARY_REPAIR_TARGET_MATCH = "repair target match"
_SUMMARY_REPAIR_TARGET_SNAPSHOT_CONSISTENCY = "repair target snapshot consistency"
_SUMMARY_PER_FILE_LAYOUT = "per-file layout"
_SUMMARY_PATCH_MEMBER_PATHS = "patch member paths"
_SUMMARY_PATCH_ASCII = "patch ascii"
_SUMMARY_LINE_LENGTH = "line length"
_SUMMARY_DOCS_GATE = "docs gate"
_SUMMARY_GIT_APPLY = "git apply"
_SUMMARY_PYTHON_COMPILE = "python compile"
_SUMMARY_JAVASCRIPT_SYNTAX = "javascript syntax"
_SUMMARY_MONOLITH = "monolith"
_SUMMARY_PYTEST_GATE = "pytest gate"
_SUMMARY_RUFF_GATE = "ruff gate"
_SUMMARY_MYPY_GATE = "mypy gate"
_SUMMARY_TYPESCRIPT_GATE = "typescript gate"
_SUMMARY_BIOME_GATE = "biome gate"
_SUMMARY_VALIDATION = "validation error"
_SUMMARY_GENERIC = "generic validator failure"

_PHB_PREVALIDATOR_TAGS: tuple[tuple[str, str], ...] = (
    ("toolkit_resolution_failed:", _SUMMARY_TOOLKIT),
    ("instructions_placeholder_invalid:", _SUMMARY_INSTRUCTIONS_EXTENSION),
    ("zip_issue_missing_or_invalid:", _SUMMARY_ISSUE_NUMBER_FILE),
    ("zip_target_missing_or_invalid:", _SUMMARY_TARGET_FILE),
    ("repair_target_missing_or_invalid:", _SUMMARY_REPAIR_TARGET_SOURCE),
    ("repair_workspace_snapshot_missing:", _SUMMARY_REPAIR_TARGET_SNAPSHOT_CONSISTENCY),
)

_VALIDATOR_RULE_TAGS: tuple[tuple[str, str], ...] = (
    ("INSTRUCTIONS_EXTENSION", _SUMMARY_INSTRUCTIONS_EXTENSION),
    ("INSTRUCTIONS_LAYOUT", _SUMMARY_INSTRUCTIONS_LAYOUT),
    ("INSTRUCTIONS_HANDOFF", _SUMMARY_INSTRUCTIONS_HANDOFF),
    ("PACK_JSON", _SUMMARY_PACK_JSON),
    ("PACK_HASH_FILE", _SUMMARY_PACK_HASH_FILE),
    ("PACK_HASH_INTEGRITY", _SUMMARY_PACK_HASH_INTEGRITY),
    ("PACK_RECOMPUTE", _SUMMARY_PACK_RECOMPUTE),
    ("PACK_REQUIRED_WIRING", _SUMMARY_PACK_WIRING),
    ("PACK_FORBIDDEN_BYPASS", _SUMMARY_PACK_FORBIDDEN_BYPASS),
    ("PACK_DOWNSTREAM_COVERAGE", _SUMMARY_PACK_DOWNSTREAM_COVERAGE),
    ("PACK_REQUIRED_VALIDATION", _SUMMARY_PACK_REQUIRED_VALIDATION),
    ("PACK_SCOPE_MAPPING", _SUMMARY_PACK_SCOPE_MAPPING),
    ("PACK_VERDICT_COVERAGE", _SUMMARY_PACK_VERDICT_COVERAGE),
    ("PATCH_EXTENSION", _SUMMARY_PATCH_EXTENSION),
    ("PATCH_BASENAME", _SUMMARY_PATCH_BASENAME),
    ("COMMIT_MESSAGE_FILE", _SUMMARY_COMMIT_MESSAGE_FILE),
    ("ISSUE_NUMBER_FILE", _SUMMARY_ISSUE_NUMBER_FILE),
    ("TARGET_FILE", _SUMMARY_TARGET_FILE),
    ("INITIAL_TARGET_SOURCE", _SUMMARY_INITIAL_TARGET_SOURCE),
    ("INITIAL_TARGET_MATCH", _SUMMARY_INITIAL_TARGET_MATCH),
    ("REPAIR_TARGET_SOURCE", _SUMMARY_REPAIR_TARGET_SOURCE),
    ("REPAIR_TARGET_MATCH", _SUMMARY_REPAIR_TARGET_MATCH),
    ("REPAIR_TARGET_SNAPSHOT_CONSISTENCY", _SUMMARY_REPAIR_TARGET_SNAPSHOT_CONSISTENCY),
    ("PER_FILE_LAYOUT", _SUMMARY_PER_FILE_LAYOUT),
    ("PATCH_MEMBER_PATHS", _SUMMARY_PATCH_MEMBER_PATHS),
    ("PATCH_ASCII", _SUMMARY_PATCH_ASCII),
    ("LINE_LENGTH", _SUMMARY_LINE_LENGTH),
    ("DOCS_GATE", _SUMMARY_DOCS_GATE),
    ("GIT_APPLY_CHECK:", _SUMMARY_GIT_APPLY),
    ("PY_COMPILE", _SUMMARY_PYTHON_COMPILE),
    ("JS_SYNTAX", _SUMMARY_JAVASCRIPT_SYNTAX),
    ("MONOLITH", _SUMMARY_MONOLITH),
    ("EXTERNAL_GATE:PYTEST", _SUMMARY_PYTEST_GATE),
    ("EXTERNAL_GATE:RUFF", _SUMMARY_RUFF_GATE),
    ("EXTERNAL_GATE:MYPY", _SUMMARY_MYPY_GATE),
    ("EXTERNAL_GATE:TYPESCRIPT", _SUMMARY_TYPESCRIPT_GATE),
    ("EXTERNAL_GATE:BIOME", _SUMMARY_BIOME_GATE),
    ("VALIDATION_ERROR", _SUMMARY_VALIDATION),
)


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


def _phb_prevalidator_tags(raw_output: str) -> list[str]:
    raw = str(raw_output or "").strip()
    if not raw:
        return []
    for prefix, tag in _PHB_PREVALIDATOR_TAGS:
        if raw.startswith(prefix):
            return [tag]
    if raw.startswith("[stderr]") or raw.startswith("repair_requires_supplemental_file:"):
        return [_SUMMARY_VALIDATION]
    return []


def _validator_rule_tags(raw_output: str) -> list[str]:
    raw = str(raw_output or "")
    matches = list(_RULE_RESULT_RE.finditer(raw))
    if not matches:
        return [_SUMMARY_GENERIC] if "RESULT: FAIL" in raw else []

    has_primary_pack_failure = any(
        str(match.group("status") or "") == "FAIL"
        and str(match.group("rule") or "").startswith("PACK_")
        and not str(match.group("rule") or "").startswith("PACK_RULE:")
        for match in matches
    )
    tags: list[str] = []
    for match in matches:
        rule = str(match.group("rule") or "").strip()
        status = str(match.group("status") or "").strip()
        tag = ""
        if status == "MANUAL_REVIEW_REQUIRED":
            tag = _SUMMARY_GENERIC
        elif rule.startswith("PACK_RULE:"):
            if not has_primary_pack_failure:
                tag = _SUMMARY_PACK_RULE
        else:
            for prefix, mapped in _VALIDATOR_RULE_TAGS:
                if rule == prefix or rule.startswith(prefix):
                    tag = mapped
                    break
            if not tag:
                tag = _SUMMARY_GENERIC
        if tag:
            tags.append(tag)
    return tags or [_SUMMARY_GENERIC]


def _format_failure_summary(tags: list[str]) -> str:
    if not tags:
        return ""
    counts: dict[str, int] = {}
    ordered: list[str] = []
    for tag in tags:
        text = str(tag or "").strip()
        if not text:
            continue
        if text not in counts:
            ordered.append(text)
            counts[text] = 0
        counts[text] += 1
    parts: list[str] = []
    for tag in ordered:
        count = counts[tag]
        parts.append(f"{count}x {tag}" if count > 1 else tag)
    return " | ".join(parts)


def _failure_summary(raw_output: str, toolkit_resolution: dict[str, Any] | None) -> str:
    resolution = dict(toolkit_resolution or {})
    resolution_mode = str(resolution.get("resolution_mode") or "").strip().lower()
    resolution_error = str(resolution.get("error") or "").strip()
    tags: list[str] = []
    if resolution_error and resolution_mode == "fail-closed":
        tags.append(_SUMMARY_TOOLKIT)

    raw = str(raw_output or "").strip()
    if raw:
        phb_tags = _phb_prevalidator_tags(raw)
        if phb_tags:
            for tag in phb_tags:
                if not (tag == _SUMMARY_TOOLKIT and _SUMMARY_TOOLKIT in tags):
                    tags.append(tag)
        else:
            tags.extend(_validator_rule_tags(raw))

    if not tags:
        tags.append(_SUMMARY_GENERIC)
    return _format_failure_summary(tags)


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
