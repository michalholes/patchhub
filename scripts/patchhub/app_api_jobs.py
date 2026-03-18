from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, cast

from .app_support import _err, _ok, _utc_now, read_tail
from .command_parse import (
    CommandParseError,
    build_canonical_command,
    parse_runner_command,
)
from .gate_argv import GateArgvError, split_gate_argv, validate_gate_argv
from .issue_alloc import allocate_next_issue_id
from .job_ids import new_job_id
from .models import (
    JobMode,
    JobRecord,
    compute_commit_summary,
    compute_patch_basename,
    job_to_list_item_json,
)
from .pm_validation_runtime import build_patch_zip_pm_validation
from .run_applied_files import collect_job_applied_files
from .web_jobs_db import WebJobsDatabase
from .web_jobs_derived import read_effective_log_tail
from .web_jobs_legacy_fs import list_legacy_job_jsons, load_legacy_job_record
from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
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


def _canonical_tail_parts(job: JobRecord) -> tuple[list[str], list[str]]:
    argv = [str(item or "") for item in list(job.canonical_command or [])]
    if not argv:
        return [], []
    try:
        idx = argv.index("scripts/am_patch.py")
    except ValueError:
        return [], []
    rest = argv[idx + 1 :]
    if job.mode == "finalize_live":
        pos = list(rest)
        try:
            pos.remove("-f")
        except ValueError:
            return [], []
        try:
            return split_gate_argv(pos)
        except GateArgvError:
            return [], []
    if job.mode == "finalize_workspace":
        pos = list(rest)
        try:
            pos.remove("-w")
        except ValueError:
            return [], []
        try:
            return split_gate_argv(pos)
        except GateArgvError:
            return [], []
    if job.mode == "rerun_latest":
        pos = list(rest)
        try:
            pos.remove("-l")
        except ValueError:
            return [], []
        try:
            return split_gate_argv(pos)
        except GateArgvError:
            return [], []
    if job.mode in ("patch", "repair"):
        try:
            return split_gate_argv(list(rest))
        except GateArgvError:
            return [], []
    return [], []


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
    commit_message = getattr(job, "commit_message", "")
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
    job_id = str(job_id)
    if not job_id:
        return None
    source = getattr(self, "web_jobs_db", None)
    if isinstance(source, WebJobsDatabase):
        return source.load_job_record(job_id)
    jobs_root = _legacy_jobs_root(self)
    if jobs_root is None:
        return None
    return load_legacy_job_record(jobs_root, job_id)


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
    if not payload.get("commit_message"):
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
    except ValueError as e:
        return _err(str(e), status=400)
    except Exception:
        return _err("Cannot inspect patch zip", status=500)
    return _ok({"manifest": manifest, "pm_validation": pm_validation})


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
    ):
        return _err("Invalid mode", status=400)
    mode: JobMode = cast(JobMode, mode_s)

    runner_prefix = self.cfg.runner.command

    issue_id = str(body.get("issue_id", ""))
    commit_message = str(body.get("commit_message", ""))
    patch_path = str(body.get("patch_path", ""))
    raw_command = str(body.get("raw_command", ""))
    try:
        selected_patch_entries = _selected_patch_entries_from_body(body)
        gate_argv = _gate_argv_from_body(body)
    except ValueError as e:
        return _err(str(e), status=400)

    original_patch_path = patch_path or None
    effective_patch_path = patch_path or None
    effective_patch_kind = "original" if patch_path else None
    selected_repo_paths: list[str] = []

    if raw_command and selected_patch_entries:
        return _err("raw_command cannot be combined with selected_patch_entries", status=400)
    if raw_command and gate_argv:
        return _err("raw_command cannot be combined with gate_argv", status=400)

    if raw_command:
        try:
            parsed = parse_runner_command(raw_command)
        except CommandParseError as e:
            return _err(str(e), status=400)
        if parsed.mode != mode and parsed.mode != "patch":
            pass
        canonical = parsed.canonical_argv
        gate_argv = parsed.gate_argv
        issue_id = parsed.issue_id or issue_id
        commit_message = parsed.commit_message or commit_message
        patch_path = parsed.patch_path or patch_path
        original_patch_path = patch_path or None
        effective_patch_path = patch_path or None
        effective_patch_kind = "original" if patch_path else None
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
            )
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
            )
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
            )
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
            )
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
                patch_basename=patch_basename,
                raw_command=raw_command,
                canonical_command=canonical,
                original_patch_path=original_patch_path,
                effective_patch_path=effective_patch_path,
                effective_patch_kind=effective_patch_kind,
                selected_patch_entries=selected_patch_entries,
                selected_repo_paths=selected_repo_paths,
            )
            self.queue.enqueue(job)
            return _ok({"job_id": job_id, "job": _job_detail_json(self, job)})

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
        patch_basename=patch_basename,
        raw_command=raw_command,
        canonical_command=canonical,
        original_patch_path=original_patch_path,
        effective_patch_path=effective_patch_path,
        effective_patch_kind=effective_patch_kind,
        selected_patch_entries=selected_patch_entries,
        selected_repo_paths=selected_repo_paths,
    )
    self.queue.enqueue(job)
    return _ok({"job_id": job_id, "job": _job_detail_json(self, job)})


def api_jobs_list(self) -> tuple[int, bytes]:
    mem = self.queue.list_jobs()
    mem_by_id = {j.job_id: j for j in mem}
    source = getattr(self, "web_jobs_db", None)
    if isinstance(source, WebJobsDatabase):
        disk_raw = source.list_job_jsons(limit=200)
    else:
        jobs_root = _legacy_jobs_root(self)
        disk_raw = [] if jobs_root is None else list_legacy_job_jsons(jobs_root, limit=200)
    disk: list[JobRecord] = []
    for r in disk_raw:
        jid = str(r.get("job_id", ""))
        if not jid or jid in mem_by_id:
            continue
        j = self._load_job_from_disk(jid)
        if j is not None:
            disk.append(j)

    jobs = mem + disk
    jobs.sort(key=lambda j: str(j.created_utc or ""), reverse=True)
    return _ok({"jobs": [job_to_list_item_json(j) for j in jobs]})


def api_jobs_get(self, job_id: str) -> tuple[int, bytes]:
    try:
        job = _run_queue_get_sync(self.queue.get_job, job_id)
    except Exception:
        job = None
    if job is None:
        job = self._load_job_from_disk(job_id)
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
