from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

JobMode = Literal[
    "patch",
    "repair",
    "finalize_live",
    "finalize_workspace",
    "rerun_latest",
    "rollback",
    "revert_job",
]
JobStatus = Literal["queued", "running", "success", "fail", "canceled", "unknown"]
RunResult = Literal["success", "fail", "unknown", "canceled"]
RollbackAuthorityRole = Literal["manifest", "request", "manifest_and_request"]

_VALID_JOB_MODES = {
    "patch",
    "repair",
    "finalize_live",
    "finalize_workspace",
    "rerun_latest",
    "rollback",
    "revert_job",
}
_VALID_JOB_STATUSES = {"queued", "running", "success", "fail", "canceled", "unknown"}


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class WebJobsDbConfig:
    db_path: Path
    busy_timeout_ms: int
    connect_timeout_s: float
    startup_migration_enabled: bool
    startup_verify_enabled: bool
    cleanup_enabled: bool
    backup_destination_template: str
    backup_retain_count: int
    backup_verify_after_write: bool
    backup_restore_source_preference: tuple[str, ...]
    recovery_restore_source_preference: tuple[str, ...]
    fallback_virtual_artifacts_web_jobs_enabled: bool
    derived_virtual_artifacts_web_jobs_enabled: bool
    compatibility_enabled: bool
    retention_defaults: dict[str, int]
    retention_thresholds: dict[str, int]


@dataclass(frozen=True)
class VirtualEntry:
    rel_path: str
    is_dir: bool
    exists: bool
    size: int = 0
    mtime_unix_ms: int = 0


@dataclass(frozen=True)
class EventRow:
    seq: int
    raw_line: str
    ipc_seq: int | None
    frame_type: str | None
    frame_event: str | None


@dataclass
class RollbackAuthorityRecord:
    job_id: str
    authority_role: RollbackAuthorityRole
    manifest_version: int | None = None
    manifest_source_job_id: str | None = None
    manifest_issue_id: str | None = None
    manifest_selected_target_repo_token: str | None = None
    manifest_effective_runner_target_repo: str | None = None
    manifest_authority_kind: str | None = None
    manifest_authority_source_ref: str | None = None
    manifest_entries: list[dict[str, Any]] = field(default_factory=list)
    request_source_job_id: str | None = None
    request_scope_kind: str | None = None
    request_selected_repo_paths: list[str] = field(default_factory=list)
    request_preflight_token: str | None = None
    updated_unix_ms: int = 0

    def has_manifest(self) -> bool:
        return self.authority_role in {"manifest", "manifest_and_request"}

    def has_request(self) -> bool:
        return self.authority_role in {"request", "manifest_and_request"}

    @classmethod
    def with_manifest(
        cls,
        *,
        job_id: str,
        manifest: dict[str, Any],
        request_source_job_id: str | None = None,
        request_scope_kind: str | None = None,
        request_selected_repo_paths: list[str] | None = None,
        request_preflight_token: str | None = None,
        updated_unix_ms: int = 0,
    ) -> RollbackAuthorityRecord:
        role: RollbackAuthorityRole = (
            "manifest_and_request"
            if request_source_job_id
            or request_scope_kind
            or request_selected_repo_paths
            or request_preflight_token
            else "manifest"
        )
        return cls(
            job_id=str(job_id or ""),
            authority_role=role,
            manifest_version=_coerce_optional_int(manifest.get("version")),
            manifest_source_job_id=(
                str(manifest.get("source_job_id"))
                if manifest.get("source_job_id") is not None
                else None
            ),
            manifest_issue_id=(
                str(manifest.get("issue_id")) if manifest.get("issue_id") is not None else None
            ),
            manifest_selected_target_repo_token=(
                str(manifest.get("selected_target_repo_token"))
                if manifest.get("selected_target_repo_token") is not None
                else None
            ),
            manifest_effective_runner_target_repo=(
                str(manifest.get("effective_runner_target_repo"))
                if manifest.get("effective_runner_target_repo") is not None
                else None
            ),
            manifest_authority_kind=(
                str(manifest.get("rollback_authority_kind"))
                if manifest.get("rollback_authority_kind") is not None
                else None
            ),
            manifest_authority_source_ref=(
                str(manifest.get("rollback_authority_source_ref"))
                if manifest.get("rollback_authority_source_ref") is not None
                else None
            ),
            manifest_entries=[
                item for item in list(manifest.get("entries") or []) if isinstance(item, dict)
            ],
            request_source_job_id=request_source_job_id,
            request_scope_kind=request_scope_kind,
            request_selected_repo_paths=[
                str(item) for item in list(request_selected_repo_paths or [])
            ],
            request_preflight_token=request_preflight_token,
            updated_unix_ms=int(updated_unix_ms or 0),
        )

    @classmethod
    def with_request(
        cls,
        *,
        job_id: str,
        source_job_id: str,
        scope_kind: str,
        selected_repo_paths: list[str],
        rollback_preflight_token: str,
        manifest_record: RollbackAuthorityRecord | None = None,
        updated_unix_ms: int = 0,
    ) -> RollbackAuthorityRecord:
        if manifest_record is not None and manifest_record.has_manifest():
            return cls(
                job_id=str(job_id or ""),
                authority_role="manifest_and_request",
                manifest_version=manifest_record.manifest_version,
                manifest_source_job_id=manifest_record.manifest_source_job_id,
                manifest_issue_id=manifest_record.manifest_issue_id,
                manifest_selected_target_repo_token=(
                    manifest_record.manifest_selected_target_repo_token
                ),
                manifest_effective_runner_target_repo=(
                    manifest_record.manifest_effective_runner_target_repo
                ),
                manifest_authority_kind=manifest_record.manifest_authority_kind,
                manifest_authority_source_ref=manifest_record.manifest_authority_source_ref,
                manifest_entries=list(manifest_record.manifest_entries),
                request_source_job_id=str(source_job_id or "") or None,
                request_scope_kind=str(scope_kind or "") or None,
                request_selected_repo_paths=[str(item) for item in list(selected_repo_paths or [])],
                request_preflight_token=str(rollback_preflight_token or "") or None,
                updated_unix_ms=int(updated_unix_ms or 0),
            )
        return cls(
            job_id=str(job_id or ""),
            authority_role="request",
            manifest_version=None,
            manifest_source_job_id=None,
            manifest_issue_id=None,
            manifest_selected_target_repo_token=None,
            manifest_effective_runner_target_repo=None,
            manifest_authority_kind=None,
            manifest_authority_source_ref=None,
            manifest_entries=[],
            request_source_job_id=str(source_job_id or "") or None,
            request_scope_kind=str(scope_kind or "") or None,
            request_selected_repo_paths=[str(item) for item in list(selected_repo_paths or [])],
            request_preflight_token=str(rollback_preflight_token or "") or None,
            updated_unix_ms=int(updated_unix_ms or 0),
        )

    def manifest_payload(self) -> dict[str, Any] | None:
        if not self.has_manifest():
            return None
        return {
            "version": int(self.manifest_version or 0),
            "source_job_id": str(self.manifest_source_job_id or ""),
            "issue_id": str(self.manifest_issue_id or ""),
            "selected_target_repo_token": str(self.manifest_selected_target_repo_token or ""),
            "effective_runner_target_repo": str(self.manifest_effective_runner_target_repo or ""),
            "rollback_authority_kind": str(self.manifest_authority_kind or ""),
            "rollback_authority_source_ref": str(self.manifest_authority_source_ref or ""),
            "entries": list(self.manifest_entries),
        }

    def request_payload(self) -> dict[str, Any] | None:
        if not self.has_request():
            return None
        return {
            "source_job_id": str(self.request_source_job_id or ""),
            "scope_kind": str(self.request_scope_kind or ""),
            "selected_repo_paths": list(self.request_selected_repo_paths),
            "rollback_preflight_token": str(self.request_preflight_token or ""),
        }


@dataclass(frozen=True)
class LegacyJobSnapshot:
    job_id: str
    job_json: dict[str, Any] | None
    log_lines: list[str]
    event_lines: list[str]


def coerce_job_mode(value: Any) -> JobMode:
    raw = str(value or "patch")
    if raw not in _VALID_JOB_MODES:
        return "patch"
    return cast(JobMode, raw)


def coerce_job_status(value: Any) -> JobStatus:
    raw = str(value or "unknown")
    if raw not in _VALID_JOB_STATUSES:
        return "unknown"
    return cast(JobStatus, raw)


@dataclass
class JobRecord:
    job_id: str
    created_utc: str
    mode: JobMode
    issue_id: str
    commit_summary: str
    patch_basename: str | None
    raw_command: str
    canonical_command: list[str]
    commit_message: str | None = None
    status: JobStatus = "queued"
    created_unix_ms: int = 0
    started_utc: str | None = None
    ended_utc: str | None = None
    return_code: int | None = None
    error: str | None = None
    cancel_requested_utc: str | None = None
    cancel_ack_utc: str | None = None
    cancel_source: str | None = None
    original_patch_path: str | None = None
    effective_patch_path: str | None = None
    effective_patch_kind: str | None = None
    selected_patch_entries: list[str] = field(default_factory=list)
    selected_repo_paths: list[str] = field(default_factory=list)
    zip_target_repo: str | None = None
    selected_target_repo: str | None = None
    effective_runner_target_repo: str | None = None
    target_mismatch: bool = False
    run_start_sha: str | None = None
    run_end_sha: str | None = None
    revert_source_job_id: str | None = None
    rollback_source_job_id: str | None = None
    rollback_scope_manifest_rel_path: str | None = None
    rollback_scope_manifest_hash: str | None = None
    rollback_authority_kind: str | None = None
    rollback_authority_source_ref: str | None = None
    origin_backend_mode: str | None = None
    origin_authoritative_backend: str | None = None
    origin_backend_session_id: str | None = None
    origin_recovery_json: str | None = None
    applied_files: list[str] = field(default_factory=list)
    applied_files_source: str = "unavailable"
    last_log_seq: int = 0
    last_event_seq: int = 0
    row_rev: int = 0

    def __post_init__(self) -> None:
        if not self.created_unix_ms and self.created_utc:
            try:
                dt = datetime.strptime(self.created_utc, "%Y-%m-%dT%H:%M:%SZ")
                self.created_unix_ms = int(dt.replace(tzinfo=UTC).timestamp() * 1000)
            except ValueError:
                self.created_unix_ms = 0
        if self.rollback_source_job_id is None and self.revert_source_job_id is not None:
            self.rollback_source_job_id = self.revert_source_job_id
        if self.revert_source_job_id is None and self.rollback_source_job_id is not None:
            self.revert_source_job_id = self.rollback_source_job_id

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> JobRecord:
        return cls(
            job_id=str(payload.get("job_id", "")),
            created_utc=str(payload.get("created_utc", "")),
            created_unix_ms=_coerce_int(payload.get("created_unix_ms", 0), 0),
            mode=coerce_job_mode(payload.get("mode", "patch")),
            issue_id=str(payload.get("issue_id", "")),
            commit_summary=str(payload.get("commit_summary", "")),
            commit_message=(
                str(payload.get("commit_message"))
                if payload.get("commit_message") is not None
                else None
            ),
            patch_basename=(
                str(payload.get("patch_basename"))
                if payload.get("patch_basename") is not None
                else None
            ),
            raw_command=str(payload.get("raw_command", "")),
            canonical_command=[str(item) for item in list(payload.get("canonical_command") or [])],
            status=coerce_job_status(payload.get("status", "unknown")),
            started_utc=(
                str(payload.get("started_utc")) if payload.get("started_utc") is not None else None
            ),
            ended_utc=(
                str(payload.get("ended_utc")) if payload.get("ended_utc") is not None else None
            ),
            return_code=_coerce_optional_int(payload.get("return_code")),
            error=str(payload.get("error")) if payload.get("error") is not None else None,
            cancel_requested_utc=(
                str(payload.get("cancel_requested_utc"))
                if payload.get("cancel_requested_utc") is not None
                else None
            ),
            cancel_ack_utc=(
                str(payload.get("cancel_ack_utc"))
                if payload.get("cancel_ack_utc") is not None
                else None
            ),
            cancel_source=(
                str(payload.get("cancel_source"))
                if payload.get("cancel_source") is not None
                else None
            ),
            original_patch_path=(
                str(payload.get("original_patch_path"))
                if payload.get("original_patch_path") is not None
                else None
            ),
            effective_patch_path=(
                str(payload.get("effective_patch_path"))
                if payload.get("effective_patch_path") is not None
                else None
            ),
            effective_patch_kind=(
                str(payload.get("effective_patch_kind"))
                if payload.get("effective_patch_kind") is not None
                else None
            ),
            selected_patch_entries=[
                str(item) for item in list(payload.get("selected_patch_entries") or [])
            ],
            selected_repo_paths=[
                str(item) for item in list(payload.get("selected_repo_paths") or [])
            ],
            zip_target_repo=(
                str(payload.get("zip_target_repo"))
                if payload.get("zip_target_repo") is not None
                else None
            ),
            selected_target_repo=(
                str(payload.get("selected_target_repo"))
                if payload.get("selected_target_repo") is not None
                else None
            ),
            effective_runner_target_repo=(
                str(payload.get("effective_runner_target_repo"))
                if payload.get("effective_runner_target_repo") is not None
                else None
            ),
            target_mismatch=bool(payload.get("target_mismatch", False)),
            run_start_sha=(
                str(payload.get("run_start_sha"))
                if payload.get("run_start_sha") is not None
                else None
            ),
            run_end_sha=(
                str(payload.get("run_end_sha")) if payload.get("run_end_sha") is not None else None
            ),
            revert_source_job_id=(
                str(payload.get("revert_source_job_id"))
                if payload.get("revert_source_job_id") is not None
                else (
                    str(payload.get("rollback_source_job_id"))
                    if payload.get("rollback_source_job_id") is not None
                    else None
                )
            ),
            rollback_source_job_id=(
                str(payload.get("rollback_source_job_id"))
                if payload.get("rollback_source_job_id") is not None
                else (
                    str(payload.get("revert_source_job_id"))
                    if payload.get("revert_source_job_id") is not None
                    else None
                )
            ),
            rollback_scope_manifest_rel_path=(
                str(payload.get("rollback_scope_manifest_rel_path"))
                if payload.get("rollback_scope_manifest_rel_path") is not None
                else None
            ),
            rollback_scope_manifest_hash=(
                str(payload.get("rollback_scope_manifest_hash"))
                if payload.get("rollback_scope_manifest_hash") is not None
                else None
            ),
            rollback_authority_kind=(
                str(payload.get("rollback_authority_kind"))
                if payload.get("rollback_authority_kind") is not None
                else None
            ),
            rollback_authority_source_ref=(
                str(payload.get("rollback_authority_source_ref"))
                if payload.get("rollback_authority_source_ref") is not None
                else None
            ),
            origin_backend_mode=(
                str(payload.get("origin_backend_mode"))
                if payload.get("origin_backend_mode") is not None
                else None
            ),
            origin_authoritative_backend=(
                str(payload.get("origin_authoritative_backend"))
                if payload.get("origin_authoritative_backend") is not None
                else None
            ),
            origin_backend_session_id=(
                str(payload.get("origin_backend_session_id"))
                if payload.get("origin_backend_session_id") is not None
                else None
            ),
            origin_recovery_json=(
                str(payload.get("origin_recovery_json"))
                if payload.get("origin_recovery_json") is not None
                else None
            ),
            applied_files=[str(item) for item in list(payload.get("applied_files") or [])],
            applied_files_source=str(payload.get("applied_files_source", "unavailable")),
            last_log_seq=_coerce_int(payload.get("last_log_seq", 0), 0),
            last_event_seq=_coerce_int(payload.get("last_event_seq", 0), 0),
            row_rev=_coerce_int(payload.get("row_rev", 0), 0),
        )

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.commit_message is None:
            payload.pop("commit_message", None)
        if self.zip_target_repo is None:
            payload.pop("zip_target_repo", None)
        if self.selected_target_repo is None:
            payload.pop("selected_target_repo", None)
        if self.effective_runner_target_repo is None:
            payload.pop("effective_runner_target_repo", None)
        if self.run_start_sha is None:
            payload.pop("run_start_sha", None)
        if self.run_end_sha is None:
            payload.pop("run_end_sha", None)
        source_job_id = self.rollback_source_job_id or self.revert_source_job_id
        if source_job_id is None:
            payload.pop("rollback_source_job_id", None)
            payload.pop("revert_source_job_id", None)
        else:
            payload["rollback_source_job_id"] = source_job_id
            payload["revert_source_job_id"] = source_job_id
        if self.rollback_scope_manifest_rel_path is None:
            payload.pop("rollback_scope_manifest_rel_path", None)
        if self.rollback_scope_manifest_hash is None:
            payload.pop("rollback_scope_manifest_hash", None)
        if self.rollback_authority_kind is None:
            payload.pop("rollback_authority_kind", None)
        if self.rollback_authority_source_ref is None:
            payload.pop("rollback_authority_source_ref", None)
        if self.origin_backend_mode is None:
            payload.pop("origin_backend_mode", None)
        if self.origin_authoritative_backend is None:
            payload.pop("origin_authoritative_backend", None)
        if self.origin_backend_session_id is None:
            payload.pop("origin_backend_session_id", None)
        if self.origin_recovery_json is None:
            payload.pop("origin_recovery_json", None)
        payload["target_mismatch"] = bool(self.target_mismatch)
        return payload


def build_job_origin_fields(
    *,
    backend_mode_state: Any,
    backend_session_id: str,
    web_jobs_db_present: bool,
) -> dict[str, str | None]:
    mode = str(getattr(backend_mode_state, "mode", "") or "").strip()
    if mode not in {"db_primary", "file_emergency"}:
        mode = "db_primary" if web_jobs_db_present else "file_emergency"
    authoritative_backend = str(
        getattr(backend_mode_state, "authoritative_backend", "") or ""
    ).strip()
    if authoritative_backend not in {"db", "files"}:
        authoritative_backend = "db" if mode == "db_primary" else "files"
    recovery = getattr(backend_mode_state, "last_recovery", None)
    if not isinstance(recovery, dict):
        recovery = {}
    return {
        "origin_backend_mode": mode,
        "origin_authoritative_backend": authoritative_backend,
        "origin_backend_session_id": str(backend_session_id or ""),
        "origin_recovery_json": json.dumps(
            recovery,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
    }


def parse_origin_recovery_json(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_job_origin_fields_from_runtime(source: Any) -> dict[str, str | None]:
    return build_job_origin_fields(
        backend_mode_state=getattr(source, "backend_mode_state", None),
        backend_session_id=str(getattr(source, "_backend_session_id", "") or ""),
        web_jobs_db_present=getattr(source, "web_jobs_db", None) is not None,
    )


def compute_commit_summary(commit_message: str, *, max_len: int = 60) -> str:
    msg = str(commit_message or "")
    msg = " ".join(msg.split())
    if not msg:
        return ""
    if len(msg) <= max_len:
        return msg
    if max_len <= 3:
        return msg[:max_len]
    return msg[: max_len - 3] + "..."


def compute_patch_basename(patch_path: str) -> str | None:
    p = str(patch_path or "").strip()
    if not p:
        return None
    p = p.replace("\\", "/")
    if "/" in p:
        return p.rsplit("/", 1)[-1] or None
    return p


def job_to_list_item_json(j: JobRecord) -> dict[str, Any]:
    return {
        "job_id": j.job_id,
        "status": j.status,
        "created_utc": j.created_utc,
        "started_utc": j.started_utc,
        "ended_utc": j.ended_utc,
        "mode": j.mode,
        "issue_id": j.issue_id,
        "commit_summary": j.commit_summary,
        "patch_basename": j.patch_basename,
    }


@dataclass
class RunEntry:
    issue_id: int
    log_rel_path: str
    result: RunResult
    result_line: str | None
    mtime_utc: str
    archived_patch_rel_path: str | None = None
    diff_bundle_rel_path: str | None = None
    success_zip_rel_path: str | None = None


def run_to_list_item_json(r: RunEntry) -> dict[str, Any]:
    refs: list[str] = []
    if r.archived_patch_rel_path:
        refs.append(str(r.archived_patch_rel_path))
    if r.diff_bundle_rel_path:
        refs.append(str(r.diff_bundle_rel_path))
    if r.success_zip_rel_path:
        refs.append(str(r.success_zip_rel_path))
    return {
        "issue_id": r.issue_id,
        "result": r.result,
        "mtime_utc": r.mtime_utc,
        "log_rel_path": r.log_rel_path,
        "artifact_refs": refs,
    }


def workspace_to_list_item_json(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": int(item.get("issue_id", 0) or 0),
        "workspace_rel_path": str(item.get("workspace_rel_path", "")),
        "state": str(item.get("state", "CLEAN")),
        "busy": bool(item.get("busy", False)),
        "mtime_utc": str(item.get("mtime_utc", "")),
        "attempt": item.get("attempt"),
        "commit_summary": item.get("commit_summary"),
        "allowed_union_count": item.get("allowed_union_count"),
    }


@dataclass
class StatsWindow:
    days: int
    total: int
    success: int
    fail: int
    unknown: int


@dataclass
class AppStats:
    all_time: StatsWindow
    windows: list[StatsWindow] = field(default_factory=list)
