from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any

from patchhub import app_api_amp as _amp
from patchhub import app_api_core as _core
from patchhub import app_api_editor as _editor
from patchhub import app_api_fs as _fs
from patchhub import app_api_jobs as _jobs
from patchhub import app_api_upload as _upload
from patchhub import app_api_workspaces as _workspaces
from patchhub import app_ui as _ui
from patchhub import proc_resources
from patchhub.app_support import read_tail
from patchhub.config import AppConfig
from patchhub.fs_jail import FsJail
from patchhub.models import JobRecord
from patchhub.run_stats_store import RunStatsStore
from patchhub.targeting import resolve_targeting_runtime
from patchhub.web_jobs_backend_mode import WebJobsBackendModeState
from patchhub.web_jobs_backup import (
    create_verified_backup,
    load_web_jobs_backup_settings,
    startup_backup_required,
)
from patchhub.web_jobs_backup_scheduler import WebJobsBackupScheduler
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_legacy_fs import legacy_jobs_signature, list_legacy_job_jsons
from patchhub.web_jobs_migration import (
    _migrate as migrate_legacy_jobs,
)
from patchhub.web_jobs_migration import (
    _verify as verify_legacy_jobs,
)
from patchhub.web_jobs_recovery import (
    mark_shutdown_clean,
    record_verified_backup,
    resolve_web_jobs_backend,
)
from patchhub.web_jobs_virtual_fs import WebJobsVirtualFs

from .async_jobs_runs_indexer import AsyncJobsRunsIndexer
from .async_offload import to_thread
from .async_queue import AsyncJobQueue
from .async_runner_exec import AsyncRunnerExecutor
from .operator_info_runtime import (
    build_backend_mode_status_payload,
    store_runtime_operator_info,
)


class AsyncAppCore:
    def __init__(self, *, repo_root: Path, cfg: Any) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        if not isinstance(cfg, AppConfig):
            raise TypeError("cfg must be patchhub.config.AppConfig")
        self.jail = FsJail(
            repo_root=repo_root,
            patches_root_rel=cfg.paths.patches_root,
            crud_allowlist=cfg.paths.crud_allowlist,
            allow_crud=cfg.paths.allow_crud,
        )
        self.patches_root = self.jail.patches_root()
        self.jobs_root = self.patches_root / "artifacts" / "web_jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.web_jobs_db_cfg = load_web_jobs_db_config(repo_root, self.patches_root)
        self.backend_mode_state = WebJobsBackendModeState(
            jobs_root=self.jobs_root,
            db_path=self.web_jobs_db_cfg.db_path,
        )
        self._backend_session_id = ""
        self.web_jobs_db: WebJobsDatabase | None = None
        self.run_stats_store: RunStatsStore | None = None
        self.virtual_jobs_fs: WebJobsVirtualFs | None = None
        self.backup_scheduler = WebJobsBackupScheduler(
            repo_root=self.repo_root,
            patches_root=self.patches_root,
            db_cfg=self.web_jobs_db_cfg,
            get_mode=lambda: self.backend_mode_state.mode,
        )
        self._terminal_job_callback: (
            Callable[[JobRecord], Coroutine[object, object, None]] | None
        ) = None
        self.queue = self._build_queue(job_db=None)
        self.indexer = AsyncJobsRunsIndexer(core=self)
        self._publish_backend_mode_status()

    def _bind_queue_callbacks(self, queue: AsyncJobQueue) -> AsyncJobQueue:
        queue.set_terminal_job_callback(self._terminal_job_callback)
        return queue

    def _build_queue(self, *, job_db: WebJobsDatabase | None) -> AsyncJobQueue:
        try:
            targeting_runtime = resolve_targeting_runtime(
                repo_root=self.repo_root,
                runner_config_toml=self.cfg.runner.runner_config_toml,
                target_cfg=getattr(self.cfg, "targeting", None),
            )
            target_repo_roots = targeting_runtime.resolved_roots_by_token
        except (OSError, ValueError):
            target_repo_roots = {}
        return self._bind_queue_callbacks(
            AsyncJobQueue(
                repo_root=self.repo_root,
                lock_path=self.jail.lock_path(),
                jobs_root=self.jobs_root,
                executor=AsyncRunnerExecutor(),
                ipc_handshake_wait_s=self.cfg.runner.ipc_handshake_wait_s,
                post_exit_grace_s=self.cfg.runner.post_exit_grace_s,
                terminate_grace_s=self.cfg.runner.terminate_grace_s,
                job_db=job_db,
                patches_root=self.patches_root,
                target_repo_roots=target_repo_roots,
            )
        )

    def register_terminal_job_callback(
        self,
        callback: Callable[[JobRecord], Coroutine[object, object, None]] | None,
    ) -> None:
        self._terminal_job_callback = callback
        self._bind_queue_callbacks(self.queue)

    def register_patch_success_callback(
        self,
        callback: Callable[[JobRecord], Coroutine[object, object, None]] | None,
    ) -> None:
        self.register_terminal_job_callback(callback)

    def queue_block_reason(self) -> str | None:
        return self.backend_mode_state.queue_block_reason()

    def backend_debug_state(self) -> dict[str, Any]:
        return self.backend_mode_state.debug_payload()

    def _publish_backend_mode_status(self) -> None:
        payload = build_backend_mode_status_payload(
            mode=self.backend_mode_state.mode,
            authoritative_backend=self.backend_mode_state.authoritative_backend,
            backend_session_id=self._backend_session_id,
            recovery=self.backend_mode_state.last_recovery,
        )
        store_runtime_operator_info(
            self.patches_root,
            {"backend_mode_status": payload},
        )

    def _enable_db_primary(self, job_db: WebJobsDatabase, recovery: dict[str, Any]) -> None:
        self.web_jobs_db = job_db
        self.run_stats_store = RunStatsStore(self.web_jobs_db_cfg, self.patches_root)
        self.virtual_jobs_fs = WebJobsVirtualFs(
            db=job_db,
            enabled=self.web_jobs_db_cfg.compatibility_enabled,
        )
        self.queue = self._build_queue(job_db=job_db)
        self.backend_mode_state.activate_db_primary(recovery)
        self._publish_backend_mode_status()

    def _enable_file_emergency(self, recovery: dict[str, Any]) -> None:
        self.web_jobs_db = None
        self.run_stats_store = None
        self.virtual_jobs_fs = None
        self.queue = self._build_queue(job_db=None)
        self.backend_mode_state.activate_file_emergency(recovery)
        self._publish_backend_mode_status()

    def _maybe_create_startup_backup(self) -> None:
        if self.web_jobs_db is None:
            return
        settings = load_web_jobs_backup_settings(
            self.repo_root,
            self.patches_root,
            self.web_jobs_db_cfg,
        )
        recovery = dict(self.backend_mode_state.last_recovery)
        recovery["backup_trigger_policy"] = settings.trigger_policy
        recovery["startup_backup_created"] = False
        recovery["startup_backup_path"] = None
        recovery["startup_backup_error"] = None
        self.backend_mode_state.last_recovery = recovery
        if not startup_backup_required(settings, recovery):
            return
        try:
            result = create_verified_backup(
                db_path=self.web_jobs_db.cfg.db_path,
                patches_root=self.patches_root,
                settings=settings,
            )
        except Exception as exc:
            recovery["startup_backup_error"] = f"{type(exc).__name__}:{exc}"
            self.backend_mode_state.last_recovery = recovery
            return
        record_verified_backup(self.patches_root, backup_path=result.path)
        recovery["startup_backup_created"] = bool(result.verified)
        recovery["startup_backup_path"] = str(result.path)
        self.backend_mode_state.last_recovery = recovery

    async def startup(self) -> None:
        self.backend_mode_state.begin_resolution()
        self._publish_backend_mode_status()
        resolution = await to_thread(
            resolve_web_jobs_backend,
            repo_root=self.repo_root,
            patches_root=self.patches_root,
            jobs_root=self.jobs_root,
            db_cfg=self.web_jobs_db_cfg,
        )
        self._backend_session_id = str(resolution.session_id)
        if resolution.mode == "db_primary" and resolution.job_db is not None:
            self._enable_db_primary(resolution.job_db, resolution.recovery)
        else:
            self._enable_file_emergency(resolution.recovery)
        if self.backend_mode_state.mode == "db_primary":
            if self.web_jobs_db_cfg.startup_migration_enabled:
                await to_thread(migrate_legacy_jobs, self.repo_root)
            if self.web_jobs_db_cfg.startup_verify_enabled:
                await to_thread(verify_legacy_jobs, self.repo_root)
            await to_thread(self._maybe_create_startup_backup)
            await self.backup_scheduler.start()
        await self.queue.start()
        await self.indexer.start()

    async def shutdown(self) -> None:
        with suppress(BaseException):
            await self.backup_scheduler.stop()
        with suppress(BaseException):
            await self.indexer.stop()
        with suppress(BaseException):
            await self.queue.stop()
        if self.backend_mode_state.resolution_done and self._backend_session_id:
            await to_thread(
                mark_shutdown_clean,
                self.patches_root,
                self._backend_session_id,
                self.backend_mode_state.last_recovery,
            )

    def jobs_signature_sync(self) -> tuple[int, int]:
        if self.web_jobs_db is not None:
            return self.web_jobs_db.jobs_signature()
        return legacy_jobs_signature(self.jobs_root)

    def list_job_jsons_sync(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if self.web_jobs_db is not None:
            return self.web_jobs_db.list_job_jsons(limit=limit)
        return list_legacy_job_jsons(self.jobs_root, limit=limit)

    def list_live_job_jsons_sync(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if self.web_jobs_db is not None:
            return self.web_jobs_db.list_live_job_jsons(limit=limit)
        cap = 1_000_000 if limit is None else max(1, int(limit))
        rows = list_legacy_job_jsons(self.jobs_root, limit=cap)
        return [row for row in rows if str(row.get("status", "")) in {"queued", "running"}]

    def read_log_tail_sync(self, job_id: str, *, lines: int = 200) -> str:
        if self.web_jobs_db is not None:
            return self.web_jobs_db.read_log_tail(job_id, lines=lines)
        log_path = self.jobs_root / str(job_id) / "runner.log"
        return read_tail(
            log_path,
            lines,
            max_bytes=self.cfg.server.tail_max_bytes,
            cache_max_entries=self.cfg.server.tail_cache_max_entries,
        )

    def mark_orphaned_sync(self, job_id: str) -> JobRecord | None:
        if self.web_jobs_db is not None:
            return self.web_jobs_db.mark_orphaned(job_id)
        job = self._load_job_from_disk(job_id)
        if job is None:
            return None
        if job.status not in {"queued", "running"}:
            return job
        job.status = "fail"
        if not job.ended_utc:
            job.ended_utc = _jobs._utc_now()
        job.error = "orphaned: not in memory queue"
        job_dir = self.jobs_root / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(
            json.dumps(job.to_json(), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return job

    _autofill_scan_dir_rel = _core._autofill_scan_dir_rel
    _derive_from_filename = _core._derive_from_filename

    api_config = _core.api_config
    api_patches_latest = _core.api_patches_latest
    api_parse_command = _core.api_parse_command
    api_runs = _core.api_runs
    api_runner_tail = _core.api_runner_tail

    api_amp_schema = _amp.api_amp_schema
    api_amp_config_get = _amp.api_amp_config_get
    api_amp_config_post = _amp.api_amp_config_post

    api_editor_bootstrap = _editor.api_editor_bootstrap
    api_editor_document = _editor.api_editor_document
    api_editor_validate = _editor.api_editor_validate
    api_editor_save = _editor.api_editor_save
    api_editor_save_unsafe = _editor.api_editor_save_unsafe
    api_editor_apply_fix = _editor.api_editor_apply_fix
    api_editor_preview_action = _editor.api_editor_preview_action

    def _backend_db_probe_sync(self, memory_job_ids: set[str]) -> dict[str, object]:
        mode = str(self.backend_mode_state.mode or "")
        db_path = str(self.web_jobs_db_cfg.db_path)
        empty_summary = {
            "memory_live_job_ids": sorted(str(job_id) for job_id in memory_job_ids),
            "persisted_live_count": 0,
            "persisted_live_job_ids": [],
            "stale_live_count": 0,
            "stale_live_job_ids": [],
        }
        if mode != "db_primary":
            return {
                "status": "unavailable",
                "db_path": db_path,
                "reason": f"mode={mode or 'unknown'}",
                "live_summary": empty_summary,
            }
        if self.web_jobs_db is None:
            return {
                "status": "unavailable",
                "db_path": db_path,
                "reason": "db_uninitialized",
                "live_summary": empty_summary,
            }
        try:
            with self.web_jobs_db._store._connect() as conn:
                latest_rows = conn.execute(
                    """
                    SELECT job_id, status, issue_id_raw AS issue_id,
                           issue_id_int, mode, created_utc, started_utc,
                           ended_utc, row_rev, last_log_seq, last_event_seq,
                           error, effective_runner_target_repo
                      FROM web_jobs
                     ORDER BY created_unix_ms DESC, job_id DESC
                     LIMIT 20
                    """
                ).fetchall()
                running_rows = conn.execute(
                    """
                    SELECT job_id, status, issue_id_raw AS issue_id,
                           issue_id_int, mode, created_utc, started_utc,
                           ended_utc, row_rev, last_log_seq, last_event_seq,
                           error, effective_runner_target_repo
                      FROM web_jobs
                     WHERE status IN ('running', 'queued')
                     ORDER BY created_unix_ms DESC, job_id DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            return {
                "status": "error",
                "db_path": db_path,
                "error": f"{type(exc).__name__}:{exc}",
                "live_summary": empty_summary,
            }
        running_jobs = [dict(row) for row in running_rows]
        persisted_live_job_ids = [str(row.get("job_id", "")) for row in running_jobs]
        stale_live_job_ids = [
            job_id for job_id in persisted_live_job_ids if job_id and job_id not in memory_job_ids
        ]
        return {
            "status": "ok",
            "db_path": db_path,
            "latest_jobs": [dict(row) for row in latest_rows],
            "running_jobs": running_jobs,
            "live_summary": {
                "memory_live_job_ids": sorted(str(job_id) for job_id in memory_job_ids),
                "persisted_live_count": len(persisted_live_job_ids),
                "persisted_live_job_ids": persisted_live_job_ids,
                "stale_live_count": len(stale_live_job_ids),
                "stale_live_job_ids": stale_live_job_ids,
            },
        }

    async def diagnostics(self) -> dict[str, object]:
        qstate: Any | None
        try:
            qstate = await self.queue.state()
        except Exception:
            qstate = None

        queued = int(getattr(qstate, "queued", 0) or 0) if qstate is not None else 0
        running = int(getattr(qstate, "running", 0) or 0) if qstate is not None else 0

        try:
            mem_jobs = await self.queue.list_jobs()
        except Exception:
            mem_jobs = []
        memory_job_ids = {
            str(getattr(job, "job_id", "")) for job in mem_jobs if str(getattr(job, "job_id", ""))
        }

        def _sync_part() -> dict[str, object]:
            lock_held = False
            try:
                from patchhub.job_ids import is_lock_held

                lock_held = is_lock_held(self.jail.lock_path())
            except Exception:
                lock_held = False

            runs = _core.iter_runs(self.patches_root, self.cfg.indexing.log_filename_regex)
            if self.run_stats_store is not None:
                summary = self.run_stats_store.build_summary(self.cfg.indexing.stats_windows_days)
                runs_count = summary.count
                stats = summary.stats
            else:
                runs_count = len(runs)
                stats = _core.compute_stats(runs, self.cfg.indexing.stats_windows_days)
            usage = _core.shutil.disk_usage(str(self.patches_root))
            return {
                "lock": {
                    "path": str(Path(self.cfg.paths.patches_root) / "am_patch.lock"),
                    "held": lock_held,
                },
                "disk": {
                    "total": int(usage.total),
                    "used": int(usage.used),
                    "free": int(usage.free),
                },
                "resources": proc_resources.snapshot(),
                "runs": {"count": runs_count},
                "stats": {
                    "all_time": stats.all_time.__dict__,
                    "windows": [w.__dict__ for w in stats.windows],
                },
            }

        try:
            sync_part = await to_thread(_sync_part)
        except Exception:
            sync_part = {
                "lock": {"path": "", "held": False},
                "disk": {"total": 0, "used": 0, "free": 0},
                "runs": {"count": 0},
                "stats": {"all_time": {}, "windows": []},
                "resources": {},
            }

        backend = dict(self.backend_debug_state())
        try:
            backend["db_probe"] = await to_thread(
                self._backend_db_probe_sync,
                memory_job_ids,
            )
        except Exception as exc:
            backend["db_probe"] = {
                "status": "error",
                "db_path": str(self.web_jobs_db_cfg.db_path),
                "error": f"{type(exc).__name__}:{exc}",
                "live_summary": {
                    "memory_live_job_ids": sorted(memory_job_ids),
                    "persisted_live_count": 0,
                    "persisted_live_job_ids": [],
                    "stale_live_count": 0,
                    "stale_live_job_ids": [],
                },
            }

        return {
            "queue": {"queued": queued, "running": running},
            "backend": backend,
            **sync_part,
        }

    api_fs_list = _fs.api_fs_list
    api_fs_read_text = _fs.api_fs_read_text
    api_fs_stat = _fs.api_fs_stat
    api_fs_download = _fs.api_fs_download
    api_fs_mkdir = _fs.api_fs_mkdir
    api_fs_rename = _fs.api_fs_rename
    api_fs_delete = _fs.api_fs_delete
    api_fs_unzip = _fs.api_fs_unzip

    _job_jsonl_path_from_fields = _jobs._job_jsonl_path_from_fields
    _load_job_from_disk = _jobs._load_job_from_disk
    _job_jsonl_path = _jobs._job_jsonl_path
    _pick_tail_job = _jobs._pick_tail_job
    api_patch_zip_manifest = _jobs.api_patch_zip_manifest
    api_jobs_get = _jobs.api_jobs_get
    api_jobs_revert = _jobs.api_jobs_revert
    api_rollback_preflight = _jobs.api_rollback_preflight
    api_rollback_helper_action = _jobs.api_rollback_helper_action

    api_upload_patch = _upload.api_upload_patch
    api_workspaces = _workspaces.api_workspaces

    render_template = _ui.render_template
    render_index = _ui.render_index
    render_debug = _ui.render_debug
    render_editor = _ui.render_editor
