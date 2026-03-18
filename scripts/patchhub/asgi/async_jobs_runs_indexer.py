from __future__ import annotations

import asyncio
import json
import os
import re
import stat as statlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Any

from patchhub.app_support import compute_success_archive_rel
from patchhub.indexing import compute_stats, iter_runs_with_signature
from patchhub.models import (
    RunEntry,
    job_to_list_item_json,
    run_to_list_item_json,
    workspace_to_list_item_json,
)
from patchhub.workspace_inventory import list_workspaces

from .async_offload import to_thread


@dataclass(frozen=True)
class IndexerSnapshot:
    jobs_items: list[dict[str, Any]]
    runs_items: list[dict[str, Any]]
    workspaces_items: list[dict[str, Any]]
    header_body: dict[str, Any]
    jobs_sig: str
    runs_sig: str
    workspaces_sig: str
    header_sig: str
    snapshot_sig: str
    seq: int = 0


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _etag_sig_jobs(*, disk_sig: tuple[int, int], mem: list[Any]) -> str:
    mem_parts: list[str] = []
    for j in sorted(mem, key=lambda x: str(getattr(x, "job_id", ""))):
        jid = str(getattr(j, "job_id", ""))
        st = str(getattr(j, "status", ""))
        isu = str(getattr(j, "issue_id", ""))
        su = str(getattr(j, "started_utc", ""))
        eu = str(getattr(j, "ended_utc", ""))
        mem_parts.append("|".join([jid, st, isu, su, eu]))
    mem_sig = sha1("\n".join(mem_parts).encode("utf-8")).hexdigest()
    return f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"


def build_header_summary(
    *,
    core: Any,
    queued: int,
    running: int,
    lock_held: bool,
    base_runs: list[RunEntry],
) -> dict[str, Any]:
    stats = compute_stats(base_runs, core.cfg.indexing.stats_windows_days)
    return {
        "queue": {"queued": int(queued), "running": int(running)},
        "lock": {
            "path": str(Path(core.cfg.paths.patches_root) / "am_patch.lock"),
            "held": bool(lock_held),
        },
        "runs": {"count": len(base_runs)},
        "stats": {
            "all_time": stats.all_time.__dict__,
            "windows": [w.__dict__ for w in stats.windows],
        },
    }


def build_header_sig(header_body: dict[str, Any]) -> str:
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

            mt = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
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
    def __init__(self, *, core: Any) -> None:
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

    def get_jobs(self) -> tuple[str, list[dict[str, Any]]] | None:
        snap = self._snap
        if snap is None:
            return None
        return snap.jobs_sig, list(snap.jobs_items)

    def get_runs(self) -> tuple[str, list[dict[str, Any]]] | None:
        snap = self._snap
        if snap is None:
            return None
        return snap.runs_sig, list(snap.runs_items)

    def get_ui_snapshot(self) -> IndexerSnapshot | None:
        return self._snap

    async def force_rescan(self) -> None:
        async with self._mu:
            self._force = True
        self._wake.set()

    async def _run_loop(self) -> None:
        poll = int(getattr(self._core.cfg.indexing, "poll_interval_seconds", 2) or 2)
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
        queued = int(getattr(qstate, "queued", 0) or 0) if qstate is not None else 0
        running = int(getattr(qstate, "running", 0) or 0) if qstate is not None else 0

        def _sync_build() -> IndexerSnapshot:
            disk_sig = self._core.jobs_signature_sync()
            disk_raw = self._core.list_job_jsons_sync(limit=200)
            jobs_sig = _etag_sig_jobs(disk_sig=disk_sig, mem=mem)

            mem_by_id = {str(getattr(j, "job_id", "")) for j in mem}
            disk_jobs: list[Any] = []

            for r in disk_raw:
                jid = str(r.get("job_id", ""))
                if not jid or jid in mem_by_id:
                    continue
                j = self._core._load_job_from_disk(jid)
                if j is None:
                    continue

                status = str(getattr(j, "status", ""))
                if status in ("queued", "running"):
                    j.status = "fail"
                    j.ended_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    j.error = "orphaned: not in memory queue"
                    self._core.mark_orphaned_sync(jid)

                disk_jobs.append(j)

            jobs = list(mem) + disk_jobs
            jobs.sort(key=lambda j: str(getattr(j, "created_utc", "")) or "", reverse=True)
            jobs_items = [job_to_list_item_json(j) for j in jobs]

            base_sig, base_runs = iter_runs_with_signature(
                self._core.patches_root,
                self._core.cfg.indexing.log_filename_regex,
            )

            canceled_runs, canceled_sig = self._build_canceled_runs_sync()
            runs_sig = (
                f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}"
                f":c={canceled_sig[0]}:{canceled_sig[1]}"
            )

            runs = list(base_runs) + canceled_runs
            runs.sort(key=lambda r: (r.mtime_utc, r.issue_id), reverse=True)
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

            workspaces_sig, workspaces_raw = list_workspaces(self._core, mem_jobs=mem)
            workspaces_items = [workspace_to_list_item_json(it) for it in workspaces_raw]

            header_body = build_header_summary(
                core=self._core,
                queued=queued,
                running=running,
                lock_held=bool(lock_held),
                base_runs=base_runs,
            )
            header_sig = build_header_sig(header_body)
            snapshot_sig = "|".join([jobs_sig, runs_sig, workspaces_sig, header_sig])

            return IndexerSnapshot(
                jobs_items=jobs_items,
                runs_items=runs_items,
                workspaces_items=workspaces_items,
                header_body=header_body,
                jobs_sig=jobs_sig,
                runs_sig=runs_sig,
                workspaces_sig=workspaces_sig,
                header_sig=header_sig,
                snapshot_sig=snapshot_sig,
            )

        try:
            snap = await to_thread(_sync_build)
            if not force and self._snap is not None:
                prev = self._snap
                if (
                    prev.jobs_sig == snap.jobs_sig
                    and prev.runs_sig == snap.runs_sig
                    and prev.workspaces_sig == snap.workspaces_sig
                    and prev.header_sig == snap.header_sig
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
            max_rev = max(max_rev, int(raw.get("row_rev", 0) or 0))
        out.sort(key=lambda r: (r.mtime_utc, r.issue_id), reverse=True)
        return out, (count, max_rev)
