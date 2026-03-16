from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from am_patch.errors import RunnerError


@dataclass
class RunResult:
    lock: Any | None = None
    exit_code: int = 1
    unified_mode: bool = False
    patch_script: Path | None = None
    used_patch_for_zip: Path | None = None
    files_for_fail_zip: list[str] = field(default_factory=list)
    failed_patch_blobs_for_zip: list[tuple[str, bytes]] = field(default_factory=list)
    patch_applied_successfully: bool = False
    applied_ok_count: int = 0
    rollback_ckpt_for_posthook: Any | None = None
    rollback_ws_for_posthook: Any | None = None
    issue_diff_base_sha: str | None = None
    issue_diff_paths: list[str] = field(default_factory=list)
    delete_workspace_after_archive: bool = False
    ws_for_posthook: Any | None = None
    push_ok_for_posthook: bool | None = None
    final_commit_sha: str | None = None
    final_pushed_files: list[str] | None = None
    final_fail_stage: str | None = None
    final_fail_reason: str | None = None
    final_fail_detail: str | None = None
    final_fail_fingerprint: str | None = None
    primary_fail_stage: str | None = None
    primary_fail_reason: str | None = None
    secondary_failures: list[tuple[str, str]] = field(default_factory=list)


def build_run_result(
    *,
    lock: Any | None,
    exit_code: int,
    unified_mode: bool,
    patch_script: Path | None,
    used_patch_for_zip: Path | None,
    files_for_fail_zip: list[str],
    failed_patch_blobs_for_zip: list[tuple[str, bytes]],
    patch_applied_successfully: bool,
    applied_ok_count: int,
    rollback_ckpt_for_posthook: Any | None,
    rollback_ws_for_posthook: Any | None,
    issue_diff_base_sha: str | None,
    issue_diff_paths: list[str],
    delete_workspace_after_archive: bool,
    ws_for_posthook: Any | None,
    push_ok_for_posthook: bool | None,
    final_commit_sha: str | None,
    final_pushed_files: list[str] | None,
    final_fail_stage: str | None = None,
    final_fail_reason: str | None = None,
    final_fail_detail: str | None = None,
    final_fail_fingerprint: str | None = None,
    primary_fail_stage: str | None = None,
    primary_fail_reason: str | None = None,
    secondary_failures: list[tuple[str, str]] | None = None,
) -> RunResult:
    return RunResult(
        lock=lock,
        exit_code=exit_code,
        unified_mode=unified_mode,
        patch_script=patch_script,
        used_patch_for_zip=used_patch_for_zip,
        files_for_fail_zip=list(files_for_fail_zip),
        failed_patch_blobs_for_zip=list(failed_patch_blobs_for_zip),
        patch_applied_successfully=patch_applied_successfully,
        applied_ok_count=applied_ok_count,
        rollback_ckpt_for_posthook=rollback_ckpt_for_posthook,
        rollback_ws_for_posthook=rollback_ws_for_posthook,
        issue_diff_base_sha=issue_diff_base_sha,
        issue_diff_paths=list(issue_diff_paths),
        delete_workspace_after_archive=delete_workspace_after_archive,
        ws_for_posthook=ws_for_posthook,
        push_ok_for_posthook=push_ok_for_posthook,
        final_commit_sha=final_commit_sha,
        final_pushed_files=(
            list(final_pushed_files) if isinstance(final_pushed_files, list) else None
        ),
        final_fail_stage=final_fail_stage,
        final_fail_reason=final_fail_reason,
        final_fail_detail=final_fail_detail,
        final_fail_fingerprint=final_fail_fingerprint,
        primary_fail_stage=primary_fail_stage,
        primary_fail_reason=primary_fail_reason,
        secondary_failures=list(secondary_failures or []),
    )


def _normalize_failure_summary(
    *,
    error: RunnerError,
    primary_fail_stage: str | None,
    secondary_failures: list[tuple[str, str]],
    parse_gate_list: Any,
    stage_rank: Any,
) -> tuple[str, str]:
    final_fail_stage = str(error.stage)
    final_fail_reason = str(error.message)
    stages: list[str] = []

    if primary_fail_stage == "PATCH":
        stages.append("PATCH_APPLY")

    for stage_name, _message in secondary_failures:
        if stage_name == "PROMOTION":
            stages.append("PROMOTE")
        elif stage_name == "SCOPE":
            stages.append("SCOPE")
        elif stage_name:
            stages.append(stage_name)

    if error.stage == "GATES":
        gates = parse_gate_list(str(error.message))
        for gate_name in gates:
            stages.append(f"GATE_{gate_name.upper()}")
        if not gates:
            stages.append("GATES")
        final_fail_reason = "gates failed"
    elif error.stage == "PATCH":
        stages.append("PATCH_APPLY")
        final_fail_reason = "patch apply failed"
    elif error.stage == "PREFLIGHT":
        stages.append("PREFLIGHT")
        final_fail_reason = "invalid inputs"
    elif error.stage == "PROMOTION":
        stages.append("PROMOTE")
        final_fail_reason = "promotion failed"
    elif error.stage == "SCOPE":
        stages.append("SCOPE")
        final_fail_reason = "scope failed"
    elif error.stage == "AUDIT":
        stages.append("AUDIT")
        final_fail_reason = "audit failed"
    else:
        stages.append(str(error.stage))

    uniq: list[str] = []
    for stage_name in stages:
        if stage_name and stage_name not in uniq:
            uniq.append(stage_name)
    uniq.sort(key=lambda stage_name: (stage_rank(stage_name), stage_name))
    final_fail_stage = ", ".join(uniq) if uniq else (final_fail_stage or "INTERNAL")
    return final_fail_stage, final_fail_reason
