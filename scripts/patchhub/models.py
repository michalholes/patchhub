from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

JobMode = Literal[
    "patch", "repair", "finalize_live", "finalize_workspace", "rerun_latest"
]
JobStatus = Literal["queued", "running", "success", "fail", "canceled", "unknown"]
RunResult = Literal["success", "fail", "unknown", "canceled"]

_VALID_JOB_MODES = {
    "patch",
    "repair",
    "finalize_live",
    "finalize_workspace",
    "rerun_latest",
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

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> JobRecord:
        return cls(
            job_id=str(payload.get("job_id", "")),
            created_utc=str(payload.get("created_utc", "")),
            created_unix_ms=_coerce_int(payload.get("created_unix_ms", 0), 0),
            mode=coerce_job_mode(payload.get("mode", "patch")),
            issue_id=str(payload.get("issue_id", "")),
            commit_summary=str(payload.get("commit_summary", "")),
            patch_basename=(
                str(payload.get("patch_basename"))
                if payload.get("patch_basename") is not None
                else None
            ),
            raw_command=str(payload.get("raw_command", "")),
            canonical_command=[
                str(item) for item in list(payload.get("canonical_command") or [])
            ],
            status=coerce_job_status(payload.get("status", "unknown")),
            started_utc=(
                str(payload.get("started_utc"))
                if payload.get("started_utc") is not None
                else None
            ),
            ended_utc=(
                str(payload.get("ended_utc"))
                if payload.get("ended_utc") is not None
                else None
            ),
            return_code=_coerce_optional_int(payload.get("return_code")),
            error=str(payload.get("error"))
            if payload.get("error") is not None
            else None,
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
            applied_files=[
                str(item) for item in list(payload.get("applied_files") or [])
            ],
            applied_files_source=str(
                payload.get("applied_files_source", "unavailable")
            ),
            last_log_seq=_coerce_int(payload.get("last_log_seq", 0), 0),
            last_event_seq=_coerce_int(payload.get("last_event_seq", 0), 0),
            row_rev=_coerce_int(payload.get("row_rev", 0), 0),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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
