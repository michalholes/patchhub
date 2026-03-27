from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, cast

from .app_support import _err, _ok, _utc_now, read_tail
from .command_parse import (
    CommandParseError,
    ParsedCommand,
    build_canonical_command,
    parse_runner_argv,
    parse_runner_command,
)
from .gate_argv import GateArgvError, validate_gate_argv
from .issue_alloc import allocate_next_issue_id
from .job_ids import new_job_id
from .job_record_lookup import (
    list_job_records_any_sync,
    load_job_record_any_sync,
    load_job_record_from_persistence,
)
from .models import (
    JobMode,
    JobRecord,
    compute_commit_summary,
    compute_patch_basename,
    job_to_list_item_json,
)
from .patch_inventory import derive_patch_metadata
from .pm_validation_runtime import build_patch_zip_pm_validation
from .rollback_helper_actions import (
    RollbackHelperActionError,
    run_helper_action,
)
from .rollback_preflight import (
    RollbackPreflightError,
    run_rollback_preflight,
    validate_source_job_authority,
)
from .run_applied_files import collect_job_applied_files
from .targeting import resolve_targeting_runtime, validate_selected_target_repo
from .web_jobs_derived import read_effective_log_tail
from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    ZipTargetConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
    read_target_repo_from_zip_path,
)
from .zip_patch_subset import (
    build_zip_patch_manifest,
    create_subset_zip,
    derive_subset_patch_rel_path,
    resolve_patch_zip_path,
    selected_repo_paths_from_manifest,
    validate_selected_patch_entries,
)


def _try_fill_commit_from_zip(self, patch_path: str) -> str:
    if not self.cfg.autofill.zip_commit_enabled:
        return ""
    if Path(patch_path).suffix.lower() != ".zip":
        return ""
    prefix = self.cfg.paths.patches_root.rstrip("/")
    rel = patch_path
    if rel.startswith(prefix + "/"):
        rel = rel[len(prefix) + 1 :]
    try:
        zpath = self.jail.resolve_rel(rel)
    except Exception:
        return ""
    if not zpath.exists() or not zpath.is_file():
        return ""
    zcfg = ZipCommitConfig(
        enabled=True,
        filename=self.cfg.autofill.zip_commit_filename,
        max_bytes=self.cfg.autofill.zip_commit_max_bytes,
        max_ratio=self.cfg.autofill.zip_commit_max_ratio,
    )
    msg, _err_reason = read_commit_message_from_zip_path(zpath, zcfg)
    return msg or ""


def _try_fill_issue_from_zip(self, patch_path: str) -> str:
    if not self.cfg.autofill.zip_issue_enabled:
        return ""
    if Path(patch_path).suffix.lower() != ".zip":
        return ""
    prefix = self.cfg.paths.patches_root.rstrip("/")
    rel = patch_path
    if rel.startswith(prefix + "/"):
        rel = rel[len(prefix) + 1 :]
    try:
        zpath = self.jail.resolve_rel(rel)
    except Exception:
        return ""
    if not zpath.exists() or not zpath.is_file():
        return ""
    zcfg = ZipIssueConfig(
        enabled=True,
        filename=self.cfg.autofill.zip_issue_filename,
        max_bytes=self.cfg.autofill.zip_issue_max_bytes,
        max_ratio=self.cfg.autofill.zip_issue_max_ratio,
    )
    zid, _err_reason = read_issue_number_from_zip_path(zpath, zcfg)
    return zid or ""


def _targeting_runtime(self):
    return resolve_targeting_runtime(
        repo_root=self.repo_root,
        runner_config_toml=self.cfg.runner.runner_config_toml,
        target_cfg=getattr(self.cfg, "targeting", None),
    )


def _resolved_target_repo_token(runtime: Any, requested_target_repo: str | None) -> str:
    token = str(requested_target_repo or "").strip()
    if token:
        return token
    return str(runtime.default_target_repo or "").strip()


def _load_job_record_any(self, job_id: str) -> JobRecord | None:
    def current_job_lookup(current_job_id: str) -> JobRecord | None:
        try:
            return _run_queue_get_sync(self.queue.get_job, current_job_id)
        except Exception:
            return None

    return load_job_record_any_sync(
        job_id,
        current_job_lookup=current_job_lookup,
        job_db=getattr(self, "web_jobs_db", None),
        jobs_root=_legacy_jobs_root(self),
    )


def _job_has_revert_fields(job: JobRecord) -> bool:
    try:
        validate_source_job_authority(job)
    except RollbackPreflightError:
        return False
    return True


def _parsed_canonical_command(job: JobRecord) -> ParsedCommand | None:
    argv = [str(item or "") for item in list(job.canonical_command or [])]
    if not argv:
        return None
    try:
        return parse_runner_argv(argv)
    except CommandParseError:
        return None


def _target_flag_from_job(job: JobRecord) -> str | None:
    parsed = _parsed_canonical_command(job)
    if parsed is None:
        return None
    token = str(parsed.target_repo or "").strip()
    return token or None


def _canonical_tail_parts(job: JobRecord) -> tuple[list[str], list[str]]:
    parsed = _parsed_canonical_command(job)
    if parsed is None:
        return [], []
    if parsed.mode == "finalize_live":
        return [parsed.commit_message], list(parsed.gate_argv)
    if parsed.mode == "finalize_workspace":
        return [parsed.issue_id], list(parsed.gate_argv)
    parts = [parsed.issue_id, parsed.commit_message]
    if parsed.patch_path:
        parts.append(parsed.patch_path)
    return parts, list(parsed.gate_argv)


def _zip_target_config() -> ZipTargetConfig:
    return ZipTargetConfig(
        enabled=True,
        filename="target.txt",
        max_bytes=128,
        max_ratio=200,
    )


def _resolve_patch_zip_path_for_target(self, patch_path: str) -> Path | None:
    raw = str(patch_path or "").strip()
    if not raw or Path(raw).suffix.lower() != ".zip":
        return None
    prefix = self.cfg.paths.patches_root.rstrip("/")
    rel = raw
    if rel.startswith(prefix + "/"):
        rel = rel[len(prefix) + 1 :]
    try:
        zpath = self.jail.resolve_rel(rel)
    except Exception:
        return None
    if not zpath.exists() or not zpath.is_file():
        return None
    return zpath


def _read_zip_target_from_patch_path(self, patch_path: str) -> str | None:
    zpath = _resolve_patch_zip_path_for_target(self, patch_path)
    if zpath is None:
        return None
    value, _err_reason = read_target_repo_from_zip_path(zpath, _zip_target_config())
    return value


def _selected_patch_entries_from_body(body: dict[str, Any]) -> list[str]:
    raw = body.get("selected_patch_entries")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("selected_patch_entries must be a JSON array")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item or "")
        if not name or name in seen:
            continue
        out.append(name)
        seen.add(name)
    return out


def _gate_argv_from_body(body: dict[str, Any]) -> list[str]:
    raw = body.get("gate_argv")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("gate_argv must be a JSON array")
    try:
        return validate_gate_argv([str(item or "") for item in raw])
    except GateArgvError as e:
        raise ValueError(str(e)) from e


def _job_commit_message_from_canonical(job: JobRecord) -> str:
    pos, _gate = _canonical_tail_parts(job)
    if job.mode == "finalize_live":
        if len(pos) == 1:
            return str(pos[0] or "")
        return ""
    if job.mode in ("patch", "repair", "rerun_latest") and len(pos) >= 2:
        return str(pos[1] or "")
    return ""


def _job_commit_message(job: JobRecord) -> str:
    commit_message = getattr(job, "commit_message", None)
    if commit_message:
        return str(commit_message or "")
    return _job_commit_message_from_canonical(job)


def _job_patch_path_from_canonical(job: JobRecord) -> str | None:
    pos, _gate = _canonical_tail_parts(job)
    if job.mode in ("patch", "repair", "rerun_latest") and len(pos) == 3:
        return str(pos[2] or "") or None
    return None


def _job_resolved_patch_path(job: JobRecord) -> str | None:
    if job.effective_patch_path:
        return str(job.effective_patch_path or "") or None
    if job.original_patch_path:
        return str(job.original_patch_path or "") or None
    return _job_patch_path_from_canonical(job)


def _job_jsonl_path_from_fields(self, job_id: str, mode: str, issue_id: str) -> Path:
    d = self.jobs_root / str(job_id)
    if mode in ("finalize_live", "finalize_workspace"):
        return d / "am_patch_finalize.jsonl"
    issue_s = str(issue_id or "")
    if issue_s.isdigit():
        return d / ("am_patch_issue_" + issue_s + ".jsonl")
    return d / "am_patch_finalize.jsonl"


def _legacy_jobs_root(self) -> Path | None:
    source = getattr(self, "jobs_root", None)
    if isinstance(source, Path):
        return source
    return None


def _load_job_from_disk(self, job_id: str) -> JobRecord | None:
    return load_job_record_from_persistence(
        job_id=str(job_id),
        job_db=getattr(self, "web_jobs_db", None),
        jobs_root=_legacy_jobs_root(self),
    )


def _job_jsonl_path(self, job: JobRecord) -> Path:
    d = self.jobs_root / job.job_id
    if job.mode in ("finalize_live", "finalize_workspace"):
        return d / "am_patch_finalize.jsonl"
    issue_s = str(job.issue_id or "")
    if issue_s.isdigit():
        return d / f"am_patch_issue_{issue_s}.jsonl"
    return d / "am_patch_finalize.jsonl"


def _pick_tail_job(self) -> JobRecord | None:
    jobs = self.queue.list_jobs()
    for j in jobs:
        if j.status == "running":
            return j
    return jobs[0] if jobs else None


def _job_detail_json(self, job: JobRecord) -> dict[str, Any]:
    payload = job.to_json()
    if "commit_message" not in payload:
        commit_message = _job_commit_message(job)
        if commit_message:
            payload["commit_message"] = commit_message
    if not payload.get("original_patch_path"):
        patch_path = _job_patch_path_from_canonical(job)
        if patch_path:
            payload["original_patch_path"] = patch_path
    if not payload.get("effective_patch_path"):
        patch_path = _job_resolved_patch_path(job)
        if patch_path:
            payload["effective_patch_path"] = patch_path
    if not payload.get("effective_patch_kind") and payload.get("effective_patch_path"):
        payload["effective_patch_kind"] = "original"
    if not payload.get("zip_target_repo"):
        patch_path = str(
            payload.get("effective_patch_path") or payload.get("original_patch_path") or ""
        )
        zip_target_repo = _read_zip_target_from_patch_path(self, patch_path)
        if zip_target_repo:
            payload["zip_target_repo"] = zip_target_repo
    if "target_mismatch" not in payload:
        payload["target_mismatch"] = bool(
            payload.get("zip_target_repo")
            and payload.get("selected_target_repo")
            and payload.get("zip_target_repo") != payload.get("selected_target_repo")
        )

    jobs_root = getattr(self, "jobs_root", self.patches_root / "artifacts" / "web_jobs")
    files, source = collect_job_applied_files(
        patches_root=self.patches_root,
        jobs_root=jobs_root,
        job=job,
        job_db=getattr(self, "web_jobs_db", None),
    )
    payload["applied_files"] = files
    payload["applied_files_source"] = source
    return payload


def api_patch_zip_manifest(self, qs: dict[str, str]) -> tuple[int, bytes]:
    patch_path = str(qs.get("path", "")).strip()
    if not patch_path:
        return _err("Missing path", status=400)
    try:
        _rel, zpath = resolve_patch_zip_path(
            jail=self.jail,
            patches_root_rel=self.cfg.paths.patches_root,
            patch_path=patch_path,
        )
        manifest = build_zip_patch_manifest(patch_path=patch_path, zpath=zpath)
        pm_validation = build_patch_zip_pm_validation(self, patch_path)
        metadata = derive_patch_metadata(self, filename=zpath.name, path=zpath)
    except ValueError as e:
        return _err(str(e), status=400)
    except Exception:
        return _err("Cannot inspect patch zip", status=500)
    return _ok(
        {
            "manifest": manifest,
            "pm_validation": pm_validation,
            "derived_issue": metadata.derived_issue,
            "derived_commit_message": metadata.derived_commit_message,
            "derived_target_repo": metadata.derived_target_repo,
        }
    )


def _queue_block_reason(self) -> str | None:
    source = getattr(self, "queue_block_reason", None)
    if callable(source):
        try:
            reason = source()
        except Exception:
            return "Backend mode selection is not finished"
        if reason:
            return str(reason)
    return None


def _all_job_records_for_rollback(self, *, limit: int = 5000) -> list[JobRecord]:
    return list_job_records_any_sync(
        current_jobs=getattr(self.queue, "_jobs", {}).values(),
        job_db=getattr(self, "web_jobs_db", None),
        jobs_root=_legacy_jobs_root(self),
        limit=limit,
    )


def _rollback_scope_kind_from_body(body: dict[str, Any]) -> str:
    return str(body.get("rollback_scope_kind", "")).strip()


def _rollback_selected_paths_from_body(body: dict[str, Any]) -> list[str]:
    raw = body.get("rollback_selected_repo_paths")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("rollback_selected_repo_paths must be a JSON array")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _write_rollback_request(job_dir: Path, payload: dict[str, Any]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "rollback_request.json"
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _run_source_job_preflight(
    self,
    source_job: JobRecord,
    *,
    scope_kind: str,
    selected_repo_paths: list[str],
) -> dict[str, Any]:
    rel_path, manifest_hash, _kind, _source_ref = validate_source_job_authority(source_job)
    return run_rollback_preflight(
        jobs_root=self.jobs_root,
        target_repo_roots=dict(getattr(self.queue, "_target_repo_roots", {})),
        source_job=source_job,
        source_manifest_rel_path=rel_path,
        source_manifest_hash=manifest_hash,
        scope_kind=scope_kind,
        selected_repo_paths=selected_repo_paths,
        all_jobs=_all_job_records_for_rollback(self),
    )


def _api_jobs_enqueue_rollback(self, body: dict[str, Any]) -> tuple[int, bytes]:
    if str(body.get("raw_command", "")).strip():
        return _err("rollback mode MUST NOT consume raw_command", status=400)
    source_job_id = str(body.get("rollback_source_job_id", "")).strip()
    token = str(body.get("rollback_preflight_token", "")).strip()
    scope_kind = _rollback_scope_kind_from_body(body)
    try:
        selected_repo_paths = _rollback_selected_paths_from_body(body)
    except ValueError as exc:
        return _err(str(exc), status=400)
    if not source_job_id:
        return _err("Missing rollback_source_job_id", status=400)
    if not token:
        return _err("Missing rollback_preflight_token", status=400)
    source_job = _load_job_record_any(self, source_job_id)
    if source_job is None:
        return _err("Source job not found", status=404)
    try:
        preflight = _run_source_job_preflight(
            self,
            source_job,
            scope_kind=scope_kind,
            selected_repo_paths=selected_repo_paths,
        )
    except (RollbackPreflightError, ValueError) as exc:
        return _err(str(exc), status=409)
    if str(preflight.get("rollback_preflight_token") or "") != token:
        return _err("rollback state changed after preview", status=409)
    if not bool(preflight.get("can_execute")):
        return _err("rollback cannot execute until guided blockers are resolved", status=409)
    job_id = new_job_id()
    issue_id = str(source_job.issue_id or "")
    commit_summary = compute_commit_summary(
        f"Roll-back {source_job.job_id}: {source_job.commit_summary}"
    )
    if not commit_summary:
        commit_summary = f"Roll-back {source_job.job_id}"
    job_dir = self.jobs_root / job_id
    try:
        _write_rollback_request(
            job_dir,
            {
                "source_job_id": source_job_id,
                "scope_kind": str(preflight.get("scope_kind") or ""),
                "selected_repo_paths": list(preflight.get("selected_repo_paths") or []),
                "rollback_preflight_token": token,
            },
        )
    except Exception:
        return _err("Cannot persist rollback request", status=500)
    job = JobRecord(
        job_id=job_id,
        created_utc=_utc_now(),
        mode="rollback",
        issue_id=issue_id,
        commit_summary=commit_summary,
        commit_message=f"Roll-back {source_job.job_id}",
        patch_basename=None,
        raw_command=f"patchhub rollback {source_job.job_id}",
        canonical_command=["patchhub", "rollback", source_job.job_id],
        effective_runner_target_repo=str(source_job.effective_runner_target_repo or ""),
        rollback_source_job_id=source_job.job_id,
    )
    _run_queue_enqueue_sync(self.queue.enqueue, job)
    return _ok({"job_id": job_id, "job": _job_detail_json(self, job)})


def api_jobs_enqueue(self, body: dict[str, Any]) -> tuple[int, bytes]:
    blocked = _queue_block_reason(self)
    if blocked is not None:
        return _err(blocked, status=409)
    mode_s = str(body.get("mode", "patch"))
    if mode_s not in (
        "patch",
        "repair",
        "finalize_live",
        "finalize_workspace",
        "rerun_latest",
        "rollback",
    ):
        return _err("Invalid mode", status=400)
    mode: JobMode = cast(JobMode, mode_s)

    runner_prefix = self.cfg.runner.command
    issue_id = str(body.get("issue_id", ""))
    commit_message = str(body.get("commit_message", ""))
    patch_path = str(body.get("patch_path", ""))
    raw_command = str(body.get("raw_command", ""))
    target_repo = str(body.get("target_repo", "")).strip()
    try:
        runtime = _targeting_runtime(self)
        target_options = runtime.options
        selected_patch_entries = _selected_patch_entries_from_body(body)
        gate_argv = _gate_argv_from_body(body)
    except (OSError, ValueError) as e:
        return _err(str(e), status=400)

    original_patch_path = patch_path or None
    effective_patch_path = patch_path or None
    effective_patch_kind = "original" if patch_path else None
    selected_repo_paths: list[str] = []
    zip_target_repo: str | None = None
    selected_target_repo: str | None = target_repo or None
    effective_runner_target_repo: str | None = None
    target_mismatch = False

    if mode == "rollback":
        return _api_jobs_enqueue_rollback(self, body)

    if raw_command and selected_patch_entries:
        return _err("raw_command cannot be combined with selected_patch_entries", status=400)
    if raw_command and gate_argv:
        return _err("raw_command cannot be combined with gate_argv", status=400)
    if raw_command and target_repo:
        return _err("raw_command cannot be combined with target_repo", status=400)
    if target_repo:
        try:
            target_repo = validate_selected_target_repo(target_repo, target_options)
        except ValueError as e:
            return _err(str(e), status=400)

    if raw_command:
        try:
            parsed = parse_runner_command(raw_command)
        except CommandParseError as e:
            return _err(str(e), status=400)
        if parsed.mode != mode:
            return _err("raw_command mode does not match mode", status=400)
        mode = parsed.mode
        canonical = parsed.canonical_argv
        gate_argv = parsed.gate_argv
        issue_id = parsed.issue_id
        commit_message = parsed.commit_message
        patch_path = parsed.patch_path
        original_patch_path = patch_path or None
        effective_patch_path = patch_path or None
        effective_patch_kind = "original" if patch_path else None
        if parsed.target_repo:
            try:
                effective_runner_target_repo = validate_selected_target_repo(
                    parsed.target_repo,
                    target_options,
                )
            except ValueError as e:
                return _err(str(e), status=400)
        effective_runner_target_repo = _resolved_target_repo_token(
            runtime,
            effective_runner_target_repo,
        )
        zip_target_repo = _read_zip_target_from_patch_path(self, patch_path)
    else:
        if mode == "finalize_live":
            if not commit_message:
                return _err("Missing finalize_live message", status=400)
            canonical = build_canonical_command(
                runner_prefix,
                mode,
                "",
                commit_message,
                "",
                gate_argv,
                target_repo=target_repo,
            )
            effective_runner_target_repo = _resolved_target_repo_token(runtime, target_repo)
        elif mode == "finalize_workspace":
            if not issue_id or not issue_id.isdigit():
                return _err("Missing/invalid issue_id", status=400)
            canonical = build_canonical_command(
                runner_prefix,
                mode,
                issue_id,
                "",
                "",
                gate_argv,
                target_repo=target_repo,
            )
            effective_runner_target_repo = _resolved_target_repo_token(runtime, target_repo)
        elif mode == "rerun_latest":
            if not issue_id or not issue_id.isdigit():
                return _err("Missing/invalid issue_id", status=400)
            if not commit_message:
                return _err("Missing commit_message", status=400)
            canonical = build_canonical_command(
                runner_prefix,
                mode,
                issue_id,
                commit_message,
                patch_path,
                gate_argv,
                target_repo=target_repo,
            )
            effective_runner_target_repo = _resolved_target_repo_token(runtime, target_repo)
            zip_target_repo = _read_zip_target_from_patch_path(self, patch_path)
        else:
            if not issue_id and patch_path:
                issue_id = _try_fill_issue_from_zip(self, patch_path)
            if not issue_id:
                issue_id = str(
                    allocate_next_issue_id(
                        self.patches_root,
                        self.cfg.issue.default_regex,
                        self.cfg.issue.allocation_start,
                        self.cfg.issue.allocation_max,
                    )
                )
            if not patch_path:
                return _err("Missing patch_path", status=400)
            if not commit_message:
                commit_message = _try_fill_commit_from_zip(self, patch_path)
            if not commit_message:
                return _err("Missing commit_message", status=400)

            job_id = new_job_id()
            if selected_patch_entries:
                try:
                    _rel, zpath = resolve_patch_zip_path(
                        jail=self.jail,
                        patches_root_rel=self.cfg.paths.patches_root,
                        patch_path=patch_path,
                    )
                    manifest = build_zip_patch_manifest(patch_path=patch_path, zpath=zpath)
                    selected_patch_entries = validate_selected_patch_entries(
                        manifest,
                        selected_patch_entries,
                    )
                except ValueError as e:
                    return _err(str(e), status=400)

                all_entries = [
                    str(item.get("zip_member", ""))
                    for item in list(manifest.get("entries") or [])
                    if item.get("selectable")
                ]
                selected_repo_paths = selected_repo_paths_from_manifest(
                    manifest,
                    selected_patch_entries,
                )
                if selected_patch_entries != all_entries:
                    derived_rel = derive_subset_patch_rel_path(
                        original_patch_path=patch_path,
                        job_id=job_id,
                    )
                    derived_path = self.patches_root / derived_rel
                    try:
                        create_subset_zip(
                            source_zip=zpath,
                            dest_zip=derived_path,
                            selected_patch_entries=selected_patch_entries,
                        )
                    except Exception:
                        return _err("Cannot create derived subset zip", status=500)
                    effective_patch_path = str(Path(self.cfg.paths.patches_root) / derived_rel)
                    effective_patch_kind = "derived_subset"
                else:
                    effective_patch_path = patch_path
                    effective_patch_kind = "original"
            else:
                job_id = new_job_id()

            canonical = build_canonical_command(
                runner_prefix,
                mode,
                issue_id,
                commit_message,
                str(effective_patch_path or patch_path),
                gate_argv,
                target_repo=target_repo,
            )
            effective_runner_target_repo = _resolved_target_repo_token(runtime, target_repo)
            zip_target_repo = _read_zip_target_from_patch_path(
                self,
                str(effective_patch_path or patch_path),
            )
            target_mismatch = bool(
                zip_target_repo and selected_target_repo and zip_target_repo != selected_target_repo
            )
            stored_commit_message = commit_message or None
            commit_summary = compute_commit_summary(commit_message)
            if not commit_summary:
                commit_summary = f"({mode})"
            patch_basename = compute_patch_basename(str(effective_patch_path or patch_path))
            job = JobRecord(
                job_id=job_id,
                created_utc=_utc_now(),
                mode=mode,
                issue_id=issue_id,
                commit_summary=commit_summary,
                commit_message=stored_commit_message,
                patch_basename=patch_basename,
                raw_command=raw_command,
                canonical_command=canonical,
                original_patch_path=original_patch_path,
                effective_patch_path=effective_patch_path,
                effective_patch_kind=effective_patch_kind,
                selected_patch_entries=selected_patch_entries,
                selected_repo_paths=selected_repo_paths,
                zip_target_repo=zip_target_repo,
                selected_target_repo=selected_target_repo,
                effective_runner_target_repo=effective_runner_target_repo,
                target_mismatch=target_mismatch,
            )
            _run_queue_enqueue_sync(self.queue.enqueue, job)
            return _ok({"job_id": job_id, "job": _job_detail_json(self, job)})

    target_mismatch = bool(
        zip_target_repo and selected_target_repo and zip_target_repo != selected_target_repo
    )
    stored_commit_message = commit_message or None
    commit_summary = compute_commit_summary(commit_message)
    if not commit_summary:
        commit_summary = f"({mode})"
    patch_basename = compute_patch_basename(str(effective_patch_path or patch_path))

    job_id = new_job_id()
    job = JobRecord(
        job_id=job_id,
        created_utc=_utc_now(),
        mode=mode,
        issue_id=issue_id,
        commit_summary=commit_summary,
        commit_message=stored_commit_message,
        patch_basename=patch_basename,
        raw_command=raw_command,
        canonical_command=canonical,
        original_patch_path=original_patch_path,
        effective_patch_path=effective_patch_path,
        effective_patch_kind=effective_patch_kind,
        selected_patch_entries=selected_patch_entries,
        selected_repo_paths=selected_repo_paths,
        zip_target_repo=zip_target_repo,
        selected_target_repo=selected_target_repo,
        effective_runner_target_repo=effective_runner_target_repo,
        target_mismatch=target_mismatch,
    )
    _run_queue_enqueue_sync(self.queue.enqueue, job)
    return _ok({"job_id": job_id, "job": _job_detail_json(self, job)})


def api_jobs_list(self) -> tuple[int, bytes]:
    jobs = list_job_records_any_sync(
        current_jobs=self.queue.list_jobs(),
        job_db=getattr(self, "web_jobs_db", None),
        jobs_root=_legacy_jobs_root(self),
        limit=200,
    )
    jobs.sort(key=lambda j: str(j.created_utc or ""), reverse=True)
    return _ok({"jobs": [job_to_list_item_json(j) for j in jobs]})


def api_jobs_get(self, job_id: str) -> tuple[int, bytes]:
    job = _load_job_record_any(self, job_id)
    if job is None:
        return _err("Not found", status=404)
    return _ok({"job": _job_detail_json(self, job)})


def api_jobs_log_tail(self, job_id: str, qs: dict[str, str]) -> tuple[int, bytes]:
    job = self.queue.get_job(job_id)
    if job is None:
        job = self._load_job_from_disk(job_id)
    if job is None:
        return _err("Not found", status=404)
    lines = int(qs.get("lines", "200"))
    log_path = self.jobs_root / str(job_id) / "runner.log"
    if getattr(self, "web_jobs_db", None) is not None:
        tail = read_effective_log_tail(self.web_jobs_db, job_id, lines=lines)
    else:
        tail = read_tail(
            log_path,
            lines,
            max_bytes=self.cfg.server.tail_max_bytes,
            cache_max_entries=self.cfg.server.tail_cache_max_entries,
        )
    return _ok({"job_id": job_id, "tail": tail})


def api_jobs_revert(self, job_id: str) -> tuple[int, bytes]:
    blocked = _queue_block_reason(self)
    if blocked is not None:
        return _err(blocked, status=409)
    source_job = _load_job_record_any(self, job_id)
    if source_job is None:
        return _err("Not found", status=404)
    try:
        preflight = _run_source_job_preflight(
            self,
            source_job,
            scope_kind="full",
            selected_repo_paths=[],
        )
    except (RollbackPreflightError, ValueError) as exc:
        return _err(str(exc), status=409)
    return _ok({"job": _job_detail_json(self, source_job), "rollback": preflight})


def api_rollback_preflight(self, body: dict[str, Any]) -> tuple[int, bytes]:
    blocked = _queue_block_reason(self)
    if blocked is not None:
        return _err(blocked, status=409)
    source_job_id = str(body.get("rollback_source_job_id", "")).strip()
    if not source_job_id:
        return _err("Missing rollback_source_job_id", status=400)
    source_job = _load_job_record_any(self, source_job_id)
    if source_job is None:
        return _err("Source job not found", status=404)
    try:
        preflight = _run_source_job_preflight(
            self,
            source_job,
            scope_kind=_rollback_scope_kind_from_body(body),
            selected_repo_paths=_rollback_selected_paths_from_body(body),
        )
    except (RollbackPreflightError, ValueError) as exc:
        return _err(str(exc), status=409)
    return _ok({"rollback": preflight, "job": _job_detail_json(self, source_job)})


def api_rollback_helper_action(self, body: dict[str, Any]) -> tuple[int, bytes]:
    blocked = _queue_block_reason(self)
    if blocked is not None:
        return _err(blocked, status=409)
    source_job_id = str(body.get("rollback_source_job_id", "")).strip()
    action = str(body.get("action", "")).strip()
    if not source_job_id:
        return _err("Missing rollback_source_job_id", status=400)
    if not action:
        return _err("Missing rollback helper action", status=400)
    source_job = _load_job_record_any(self, source_job_id)
    if source_job is None:
        return _err("Source job not found", status=404)
    try:
        preflight = run_helper_action(
            action=action,
            jobs_root=self.jobs_root,
            target_repo_roots=dict(getattr(self.queue, "_target_repo_roots", {})),
            source_job=source_job,
            scope_kind=_rollback_scope_kind_from_body(body),
            selected_repo_paths=_rollback_selected_paths_from_body(body),
            all_jobs=_all_job_records_for_rollback(self),
        )
    except (RollbackHelperActionError, RollbackPreflightError, ValueError) as exc:
        return _err(str(exc), status=409)
    return _ok({"rollback": preflight, "job": _job_detail_json(self, source_job)})


def _run_queue_bool_sync(
    fn: Callable[[str], Awaitable[bool]],
    job_id: str,
) -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        coro = cast("Coroutine[Any, Any, bool]", fn(job_id))
        return bool(asyncio.run(coro))
    raise RuntimeError("Legacy jobs API cannot run inside an active event loop")


def _run_queue_get_sync(
    fn: Callable[[str], JobRecord | Awaitable[JobRecord | None] | None],
    job_id: str,
) -> JobRecord | None:
    result = fn(job_id)
    if asyncio.iscoroutine(result):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            coro = cast("Coroutine[Any, Any, JobRecord | None]", result)
            return asyncio.run(coro)
        raise RuntimeError("Legacy jobs API cannot run inside an active event loop")
    return cast("JobRecord | None", result)


def _run_queue_enqueue_sync(
    fn: Callable[[JobRecord], Awaitable[None] | None],
    job: JobRecord,
) -> None:
    result = fn(job)
    if asyncio.iscoroutine(result):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            coro = cast("Coroutine[Any, Any, None]", result)
            asyncio.run(coro)
            return
        raise RuntimeError("Legacy jobs API cannot run inside an active event loop")


def api_jobs_cancel(self, job_id: str) -> tuple[int, bytes]:
    try:
        ok = _run_queue_bool_sync(self.queue.cancel, job_id)
    except Exception:
        return _err("Cannot cancel", status=409)
    if not ok:
        return _err("Cannot cancel", status=409)
    return _ok({"job_id": job_id})


def api_jobs_hard_stop(self, job_id: str) -> tuple[int, bytes]:
    try:
        ok = _run_queue_bool_sync(self.queue.hard_stop, job_id)
    except Exception:
        return _err("Cannot hard stop", status=409)
    if not ok:
        return _err("Cannot hard stop", status=409)
    return _ok({"job_id": job_id})
