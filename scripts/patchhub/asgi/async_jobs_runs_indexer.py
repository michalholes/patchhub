from __future__ import annotations

import asyncio
import json
import os
import re
import stat as statlib
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from patchhub.app_support import compute_success_archive_rel
from patchhub.indexing import compute_stats, iter_runs_with_signature
from patchhub.job_record_lookup import load_job_record_from_persistence
from patchhub.models import (
    AppStats,
    RunEntry,
    StatsWindow,
    job_to_list_item_json,
    run_to_list_item_json,
    workspace_to_list_item_json,
)
from patchhub.patch_inventory import build_patch_inventory
from patchhub.workspace_inventory import list_workspaces

from .async_offload import to_thread
from .operator_info_runtime import build_operator_info_sig, load_operator_info

if TYPE_CHECKING:
    from patchhub.asgi.async_queue import AsyncJobQueue
    from patchhub.config import AppConfig
    from patchhub.fs_jail import FsJail
    from patchhub.models import JobRecord
    from patchhub.run_stats_store import RunStatsStore
    from patchhub.web_jobs_db import WebJobsDatabase


class CoreLike(Protocol):
    cfg: AppConfig
    queue: AsyncJobQueue
    patches_root: Path
    jobs_root: Path
    repo_root: Path
    run_stats_store: RunStatsStore | None
    jail: FsJail
    web_jobs_db: WebJobsDatabase | None

    def list_live_job_jsons_sync(self, *, limit: int | None = None) -> list[dict[str, object]]: ...

    def mark_orphaned_sync(self, job_id: str) -> JobRecord | None: ...

    def jobs_signature_sync(self) -> tuple[int, int]: ...

    def list_job_jsons_sync(self, *, limit: int = 200) -> list[dict[str, object]]: ...


def _obj_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    out: dict[str, object] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if isinstance(key, str):
            out[key] = item
    return out


def _obj_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(cast(list[object], value))
    return []


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _empty_operator_info() -> dict[str, object]:
    return {"cleanup_recent_status": []}


def _empty_item_list() -> list[dict[str, object]]:
    return []


def _job_order_key(job: JobRecord) -> str:
    return str(job.created_utc or "")


def _job_id_key(job: JobRecord) -> str:
    return str(job.job_id)


def _run_order_key(run: RunEntry) -> tuple[str, int]:
    return str(run.mtime_utc), int(run.issue_id)


def _stats_window_json(window: StatsWindow) -> dict[str, object]:
    return {
        "days": int(window.days),
        "total": int(window.total),
        "success": int(window.success),
        "fail": int(window.fail),
        "unknown": int(window.unknown),
    }


def _stats_json(stats: AppStats) -> dict[str, object]:
    return {
        "all_time": _stats_window_json(stats.all_time),
        "windows": [_stats_window_json(w) for w in stats.windows],
    }


@dataclass(frozen=True)
class IndexerSnapshot:
    jobs_items: list[dict[str, object]]
    runs_items: list[dict[str, object]]
    workspaces_items: list[dict[str, object]]
    header_body: dict[str, object]
    jobs_sig: str
    runs_sig: str
    workspaces_sig: str
    header_sig: str
    snapshot_sig: str
    patches_items: list[dict[str, object]] = field(default_factory=_empty_item_list)
    patches_sig: str = ""
    operator_info: dict[str, object] = field(default_factory=_empty_operator_info)
    operator_info_sig: str = ""
    seq: int = 0


def _etag_sig_jobs(*, disk_sig: tuple[int, int], mem: list[JobRecord]) -> str:
    mem_parts: list[str] = []
    for j in sorted(mem, key=_job_id_key):
        jid = str(j.job_id)
        st = str(j.status)
        isu = str(j.issue_id)
        su = str(j.started_utc)
        eu = str(j.ended_utc)
        mem_parts.append("|".join([jid, st, isu, su, eu]))
    mem_sig = sha1("\n".join(mem_parts).encode("utf-8")).hexdigest()
    return f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"


def build_header_summary(
    *,
    core: CoreLike,
    queued: int,
    running: int,
    lock_held: bool,
    base_runs: list[RunEntry],
) -> dict[str, object]:
    try:
        store = core.run_stats_store
    except AttributeError:
        store = None
    if store is not None:
        summary = store.build_summary(core.cfg.indexing.stats_windows_days)
        runs_count = summary.count
        stats = summary.stats
    else:
        runs_count = len(base_runs)
        stats = compute_stats(base_runs, core.cfg.indexing.stats_windows_days)
    return {
        "queue": {"queued": int(queued), "running": int(running)},
        "lock": {
            "path": str(Path(core.cfg.paths.patches_root) / "am_patch.lock"),
            "held": bool(lock_held),
        },
        "runs": {"count": runs_count},
        "stats": _stats_json(stats),
    }


def build_header_sig(header_body: dict[str, object]) -> str:
    payload = json.dumps(
        header_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "header:" + sha1(payload).hexdigest()


def _latest_by_issue(
    patches_root: Path,
    dir_name: str,
    rx: re.Pattern[str],
) -> dict[int, str]:
    d = patches_root / dir_name
    try:
        it = os.scandir(d)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return {}

    best: dict[int, tuple[int, str]] = {}
    with it:
        for ent in it:
            name = ent.name
            m = rx.search(name)
            if not m:
                continue
            try:
                issue_id = int(m.group(1))
            except Exception:
                continue
            try:
                st = ent.stat()
            except Exception:
                continue
            if not statlib.S_ISREG(st.st_mode):
                continue

            mt = int(st.st_mtime_ns)
            cand = (mt, name)
            prev = best.get(issue_id)
            if prev is None or cand[0] > prev[0] or (cand[0] == prev[0] and cand[1] > prev[1]):
                best[issue_id] = cand

    out: dict[int, str] = {}
    for issue_id, (_mt, name) in best.items():
        out[issue_id] = str(Path(dir_name) / name)
    return out


def _decorate_runs_in_place(
    runs: list[RunEntry],
    *,
    patches_root: Path,
    success_zip_rel: str,
) -> None:
    success_exists = False
    if success_zip_rel:
        try:
            success_exists = (patches_root / success_zip_rel).exists()
        except Exception:
            success_exists = False

    rx_issue = re.compile(r"issue_(\\d+)")
    rx_diff = re.compile(r"issue_(\\d+)_diff")

    latest_success = _latest_by_issue(patches_root, "successful", rx_issue)
    latest_unsuccessful = _latest_by_issue(patches_root, "unsuccessful", rx_issue)
    latest_diff = _latest_by_issue(patches_root, "artifacts", rx_diff)

    for r in runs:
        issue_id = int(r.issue_id)
        archived: str | None = None
        if r.result == "success":
            archived = latest_success.get(issue_id)
        elif r.result in ("fail", "canceled"):
            archived = latest_unsuccessful.get(issue_id)

        if not archived:
            archived = latest_success.get(issue_id) or latest_unsuccessful.get(issue_id)

        r.archived_patch_rel_path = archived
        r.diff_bundle_rel_path = latest_diff.get(issue_id)
        r.success_zip_rel_path = success_zip_rel if success_exists else None


class AsyncJobsRunsIndexer:
    def __init__(self, *, core: CoreLike) -> None:
        self._core = core
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._force = False
        self._ready = False
        self._last_err: str | None = None
        self._snap: IndexerSnapshot | None = None
        self._snapshot_seq = 0
        self._snapshot_change_callback: Callable[[IndexerSnapshot], None] | None = None
        self._mu = asyncio.Lock()
        self._success_zip_rel: str = ""

        # Incremental cache for canceled runs (status + issue_id per job.json).
        self._cancel_job_cache: dict[str, tuple[int, str, int]] = {}

    async def start(self) -> None:
        if self._task is not None:
            return

        await self._init_success_zip_rel()
        await self._rebuild(reason="startup")
        self._task = asyncio.create_task(self._run_loop(), name="patchhub_indexer")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(Exception):
                await self._task
            self._task = None

    def ready(self) -> bool:
        return bool(self._ready) and self._snap is not None

    def snapshot_seq(self) -> int:
        return int(self._snapshot_seq)

    def set_snapshot_change_callback(
        self,
        callback: Callable[[IndexerSnapshot], None] | None,
    ) -> None:
        self._snapshot_change_callback = callback

    def last_error(self) -> str | None:
        return self._last_err

    def get_jobs(self) -> tuple[str, list[dict[str, object]]] | None:
        snap = self._snap
        if snap is None:
            return None
        return snap.jobs_sig, list(snap.jobs_items)

    def get_runs(self) -> tuple[str, list[dict[str, object]]] | None:
        snap = self._snap
        if snap is None:
            return None
        return snap.runs_sig, list(snap.runs_items)

    def get_ui_snapshot(self) -> IndexerSnapshot | None:
        return self._snap

    def install_external_snapshot_payload(self, payload: dict[str, object]) -> IndexerSnapshot:
        snapshot = _obj_dict(payload.get("snapshot"))
        sigs = _obj_dict(payload.get("sigs"))
        if snapshot is None:
            raise TypeError("payload.snapshot must be a mapping")
        if sigs is None:
            raise TypeError("payload.sigs must be a mapping")

        next_seq = (
            max(
                int(self._snapshot_seq),
                _as_int(payload.get("seq", 0), 0),
            )
            + 1
        )
        raw_jobs = _obj_list(snapshot.get("jobs"))
        raw_runs = _obj_list(snapshot.get("runs"))
        raw_patches = _obj_list(snapshot.get("patches"))
        raw_workspaces = _obj_list(snapshot.get("workspaces"))
        raw_header = _obj_dict(snapshot.get("header")) or {}
        raw_operator_info = _obj_dict(snapshot.get("operator_info")) or _empty_operator_info()
        snap = IndexerSnapshot(
            jobs_items=[item for item in (_obj_dict(i) for i in raw_jobs) if item is not None],
            runs_items=[item for item in (_obj_dict(i) for i in raw_runs) if item is not None],
            patches_items=[
                item for item in (_obj_dict(i) for i in raw_patches) if item is not None
            ],
            workspaces_items=[
                item for item in (_obj_dict(i) for i in raw_workspaces) if item is not None
            ],
            header_body=raw_header,
            operator_info=raw_operator_info,
            jobs_sig=str(sigs.get("jobs", "")),
            runs_sig=str(sigs.get("runs", "")),
            patches_sig=str(sigs.get("patches", "")),
            workspaces_sig=str(sigs.get("workspaces", "")),
            header_sig=str(sigs.get("header", "")),
            operator_info_sig=str(sigs.get("operator_info", "")),
            snapshot_sig=str(sigs.get("snapshot", "")),
            seq=next_seq,
        )
        self._snapshot_seq = next_seq
        self._snap = snap
        self._ready = True
        self._last_err = None
        if self._snapshot_change_callback is not None:
            self._snapshot_change_callback(snap)
        return snap

    async def force_rescan(self) -> None:
        async with self._mu:
            self._force = True
        self._wake.set()

    async def rebuild_fail_safe(self, *, reason: str) -> None:
        await self._rebuild(reason=reason)

    async def _run_loop(self) -> None:
        poll = int(self._core.cfg.indexing.poll_interval_seconds or 2)
        poll = max(1, min(poll, 3600))

        while not self._stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=float(poll))
            self._wake.clear()
            if self._stop.is_set():
                break
            await self._rebuild(reason="poll")

    async def _init_success_zip_rel(self) -> None:
        def _sync() -> str:
            runner_cfg_path = self._core.repo_root / self._core.cfg.runner.runner_config_toml
            runner_cfg_path = runner_cfg_path.resolve()
            return compute_success_archive_rel(
                self._core.repo_root,
                runner_cfg_path,
                self._core.cfg.paths.patches_root,
            )

        try:
            self._success_zip_rel = await to_thread(_sync)
        except Exception:
            self._success_zip_rel = ""

    async def _rebuild(self, *, reason: str) -> None:
        async with self._mu:
            force = bool(self._force)
            self._force = False

        mem = await self._core.queue.list_jobs()
        try:
            qstate = await self._core.queue.state()
        except Exception:
            qstate = None
        queued = int(qstate.queued) if qstate is not None else 0
        running = int(qstate.running) if qstate is not None else 0

        def _sync_build() -> IndexerSnapshot:
            mem_by_id = {str(j.job_id) for j in mem}
            disk_jobs: list[JobRecord] = []

            live_raw = self._core.list_live_job_jsons_sync()
            for r in live_raw:
                jid = str(r.get("job_id", ""))
                if not jid or jid in mem_by_id:
                    continue
                self._core.mark_orphaned_sync(jid)

            disk_sig = self._core.jobs_signature_sync()
            disk_raw = self._core.list_job_jsons_sync(limit=200)
            jobs_sig = _etag_sig_jobs(disk_sig=disk_sig, mem=mem)

            for r in disk_raw:
                jid = str(r.get("job_id", ""))
                if not jid or jid in mem_by_id:
                    continue
                j = load_job_record_from_persistence(
                    job_id=jid,
                    job_db=self._core.web_jobs_db,
                    jobs_root=self._core.jobs_root,
                )
                if j is None:
                    continue

                disk_jobs.append(j)

            jobs = list(mem) + disk_jobs
            jobs.sort(key=_job_order_key, reverse=True)
            jobs_items = [job_to_list_item_json(j) for j in jobs]

            base_sig, base_runs = iter_runs_with_signature(
                self._core.patches_root,
                self._core.cfg.indexing.log_filename_regex,
            )
            if self._core.run_stats_store is not None:
                self._core.run_stats_store.ingest_logs(
                    self._core.cfg.indexing.log_filename_regex,
                )

            canceled_runs, canceled_sig = self._build_canceled_runs_sync()
            runs_sig = (
                f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}"
                f":c={canceled_sig[0]}:{canceled_sig[1]}"
            )

            runs = list(base_runs) + canceled_runs
            runs.sort(key=_run_order_key, reverse=True)
            runs = runs[:500]
            _decorate_runs_in_place(
                runs,
                patches_root=self._core.patches_root,
                success_zip_rel=self._success_zip_rel,
            )
            runs_items = [run_to_list_item_json(r) for r in runs]

            lock_held = 0
            try:
                from patchhub.job_ids import is_lock_held

                lock_held = 1 if is_lock_held(self._core.jail.lock_path()) else 0
            except Exception:
                lock_held = 0

            patches_sig, patches_items = build_patch_inventory(self._core)
            workspaces_sig, workspaces_raw = list_workspaces(
                self._core,
                mem_jobs=mem,
            )
            workspaces_items = [workspace_to_list_item_json(it) for it in workspaces_raw]

            header_body = build_header_summary(
                core=self._core,
                queued=queued,
                running=running,
                lock_held=bool(lock_held),
                base_runs=base_runs,
            )
            header_sig = build_header_sig(header_body)
            operator_info = load_operator_info(self._core.patches_root)
            operator_info_sig = build_operator_info_sig(operator_info)
            snapshot_sig = "|".join(
                [
                    jobs_sig,
                    runs_sig,
                    patches_sig,
                    workspaces_sig,
                    header_sig,
                    operator_info_sig,
                ]
            )

            return IndexerSnapshot(
                jobs_items=jobs_items,
                runs_items=runs_items,
                patches_items=patches_items,
                workspaces_items=workspaces_items,
                header_body=header_body,
                jobs_sig=jobs_sig,
                runs_sig=runs_sig,
                patches_sig=patches_sig,
                workspaces_sig=workspaces_sig,
                header_sig=header_sig,
                snapshot_sig=snapshot_sig,
                operator_info=operator_info,
                operator_info_sig=operator_info_sig,
            )

        try:
            snap = await to_thread(_sync_build)
            if not force and self._snap is not None:
                prev = self._snap
                if (
                    prev.jobs_sig == snap.jobs_sig
                    and prev.runs_sig == snap.runs_sig
                    and prev.patches_sig == snap.patches_sig
                    and prev.workspaces_sig == snap.workspaces_sig
                    and prev.header_sig == snap.header_sig
                    and prev.operator_info_sig == snap.operator_info_sig
                ):
                    self._ready = True
                    self._last_err = None
                    return

            self._snapshot_seq += 1
            snap = replace(snap, seq=self._snapshot_seq)
            self._snap = snap
            self._ready = True
            self._last_err = None
            if self._snapshot_change_callback is not None:
                self._snapshot_change_callback(snap)
        except Exception as e:
            self._ready = False
            self._last_err = f"indexer_failed:{reason}:{type(e).__name__}:{e}"

    def _build_canceled_runs_sync(self) -> tuple[list[RunEntry], tuple[int, int]]:
        rows = self._core.list_job_jsons_sync(limit=1000000)
        out: list[RunEntry] = []
        count = 0
        max_rev = 0
        for raw in rows:
            if str(raw.get("status", "")) != "canceled":
                continue
            try:
                issue_id = int(str(raw.get("issue_id", "")))
            except Exception:
                continue
            job_id = str(raw.get("job_id", ""))
            if self._core.web_jobs_db is not None:
                event_name = self._core.web_jobs_db.legacy_event_filename(job_id)
            elif str(raw.get("mode", "")) in {"finalize_live", "finalize_workspace"}:
                event_name = "am_patch_finalize.jsonl"
            elif str(raw.get("issue_id", "")).isdigit():
                event_name = f"am_patch_issue_{str(raw.get('issue_id', ''))}.jsonl"
            else:
                event_name = "am_patch_finalize.jsonl"
            ended_utc = str(raw.get("ended_utc") or raw.get("created_utc") or "")
            out.append(
                RunEntry(
                    issue_id=issue_id,
                    log_rel_path=str(Path("artifacts") / "web_jobs" / job_id / event_name),
                    result="canceled",
                    result_line="RESULT: CANCELED",
                    mtime_utc=ended_utc,
                )
            )
            count += 1
            max_rev = max(max_rev, _as_int(raw.get("row_rev", 0), 0))
        out.sort(key=_run_order_key, reverse=True)
        return out, (count, max_rev)
