from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import Response

from patchhub.app_support import canceled_runs_signature
from patchhub.indexing import iter_runs, runs_signature
from patchhub.models import job_to_list_item_json, workspace_to_list_item_json
from patchhub.web_jobs_db import WebJobsDatabase
from patchhub.web_jobs_legacy_fs import (
    legacy_jobs_signature,
    list_legacy_job_jsons,
)
from patchhub.workspace_inventory import list_workspaces

from .async_jobs_runs_indexer import build_header_sig, build_header_summary
from .async_offload import to_thread
from .json_contract import json_head_response, json_headers, json_response

if TYPE_CHECKING:
    from .async_app_core import AsyncAppCore


def _etag_quote(token: str) -> str:
    token = str(token or "")
    return '"' + token.replace('"', "") + '"'


def _etag_matches(if_none_match: str | None, etag_value: str) -> bool:
    if if_none_match is None:
        return False
    return str(if_none_match).strip() == etag_value


def _legacy_jobs_root(core: AsyncAppCore) -> Path | None:
    source = getattr(core, "jobs_root", None)
    if isinstance(source, Path):
        return source
    return None


def _jobs_sig(*, disk_sig: tuple[int, int], mem: list[Any]) -> str:
    parts: list[str] = []
    for item in sorted(mem, key=lambda x: str(getattr(x, "job_id", ""))):
        parts.append(
            "|".join(
                [
                    str(getattr(item, "job_id", "")),
                    str(getattr(item, "status", "")),
                    str(getattr(item, "issue_id", "")),
                    str(getattr(item, "started_utc", "")),
                    str(getattr(item, "ended_utc", "")),
                ]
            )
        )
    mem_sig = sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"


async def _legacy_snapshot_payload(core: AsyncAppCore) -> dict[str, Any]:
    qstate = None
    try:
        qstate = await core.queue.state()
    except Exception:
        qstate = None
    queued = int(getattr(qstate, "queued", 0) or 0) if qstate is not None else 0
    running = int(getattr(qstate, "running", 0) or 0) if qstate is not None else 0

    job_source = getattr(core, "web_jobs_db", None)
    if isinstance(job_source, WebJobsDatabase):
        disk_sig = await to_thread(job_source.jobs_signature)
    else:
        jobs_root = _legacy_jobs_root(core)
        disk_sig = (
            (0, 0) if jobs_root is None else await to_thread(legacy_jobs_signature, jobs_root)
        )
    mem = await core.queue.list_jobs()
    mem_by_id = {str(j.job_id): j for j in mem}
    jobs_sig = _jobs_sig(disk_sig=disk_sig, mem=mem)

    def _load_disk_jobs_sync() -> list[Any]:
        if isinstance(job_source, WebJobsDatabase):
            disk_raw = job_source.list_job_jsons(limit=200)
        else:
            jobs_root = _legacy_jobs_root(core)
            disk_raw = [] if jobs_root is None else list_legacy_job_jsons(jobs_root, limit=200)
        disk_jobs: list[Any] = []
        for item in disk_raw:
            jid = str(item.get("job_id", ""))
            if not jid or jid in mem_by_id:
                continue
            job = core._load_job_from_disk(jid)
            if job is None:
                continue
            disk_jobs.append(job)
        return disk_jobs

    disk_jobs = await to_thread(_load_disk_jobs_sync)
    jobs = list(mem) + disk_jobs
    jobs.sort(key=lambda job: str(getattr(job, "created_utc", "")) or "", reverse=True)
    jobs_items = [job_to_list_item_json(job) for job in jobs]

    base_sig = await to_thread(
        runs_signature,
        core.patches_root,
        core.cfg.indexing.log_filename_regex,
    )
    canceled_source = getattr(core, "web_jobs_db", getattr(core, "jobs_root", None))
    canceled_sig = await to_thread(canceled_runs_signature, canceled_source)
    runs_sig = (
        f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}:c={canceled_sig[0]}:{canceled_sig[1]}"
    )

    runs_status, runs_bytes = await to_thread(core.api_runs, {"limit": "80"})
    runs_items: list[Any] = []
    if runs_status == 200:
        try:
            runs_payload = json.loads(runs_bytes.decode("utf-8"))
            runs_items = list(runs_payload.get("runs", []) or [])
        except Exception:
            runs_items = []

    workspaces_sig, workspaces_raw = await to_thread(list_workspaces, core, mem)
    workspaces_items = [workspace_to_list_item_json(item) for item in workspaces_raw]

    def _lock_held_sync() -> bool:
        try:
            from patchhub.job_ids import is_lock_held

            return bool(is_lock_held(core.jail.lock_path()))
        except Exception:
            return False

    lock_held = await to_thread(_lock_held_sync)
    base_runs = await to_thread(
        iter_runs,
        core.patches_root,
        core.cfg.indexing.log_filename_regex,
    )
    header_body = build_header_summary(
        core=core,
        queued=queued,
        running=running,
        lock_held=lock_held,
        base_runs=base_runs,
    )
    header_sig = build_header_sig(header_body)
    snapshot_sig = "|".join([jobs_sig, runs_sig, workspaces_sig, header_sig])
    current_seq = 0
    try:
        current_seq = int(core.indexer.snapshot_seq())
    except Exception:
        current_seq = 0
    return {
        "ok": True,
        "seq": current_seq,
        "snapshot": {
            "jobs": jobs_items,
            "runs": runs_items,
            "workspaces": workspaces_items,
            "header": header_body,
        },
        "sigs": {
            "jobs": jobs_sig,
            "runs": runs_sig,
            "workspaces": workspaces_sig,
            "header": header_sig,
            "snapshot": snapshot_sig,
        },
    }


async def handle_api_ui_snapshot(
    core: AsyncAppCore,
    request: Request,
    *,
    head_only: bool = False,
) -> Response:
    since_sig = str(request.query_params.get("since_sig", "")).strip()

    if core.indexer.ready():
        snap = core.indexer.get_ui_snapshot()
        if snap is not None:
            snapshot_sig = str(snap.snapshot_sig)
            etag = _etag_quote(snapshot_sig)
            inm = request.headers.get("if-none-match")
            if etag and _etag_matches(inm, etag):
                return Response(status_code=304, headers=json_headers({"ETag": etag}))
            if since_sig and since_sig == snapshot_sig:
                if head_only:
                    return json_head_response(200, headers={"ETag": etag})
                return json_response(
                    {"ok": True, "unchanged": True, "sig": snapshot_sig},
                    status=200,
                    headers={"ETag": etag},
                )
            if head_only:
                return json_head_response(200, headers={"ETag": etag})
            payload: dict[str, Any] = {
                "ok": True,
                "seq": int(getattr(snap, "seq", 0) or 0),
                "snapshot": {
                    "jobs": list(snap.jobs_items),
                    "runs": list(snap.runs_items[:80]),
                    "workspaces": list(snap.workspaces_items),
                    "header": dict(snap.header_body),
                },
                "sigs": {
                    "jobs": str(snap.jobs_sig),
                    "runs": str(snap.runs_sig),
                    "workspaces": str(snap.workspaces_sig),
                    "header": str(snap.header_sig),
                    "snapshot": snapshot_sig,
                },
            }
            return json_response(
                payload,
                status=200,
                headers={"ETag": etag},
            )

    payload = await _legacy_snapshot_payload(core)
    snapshot_sig = str(payload["sigs"]["snapshot"])
    etag = _etag_quote(snapshot_sig)
    inm = request.headers.get("if-none-match")
    if etag and _etag_matches(inm, etag):
        return Response(status_code=304, headers=json_headers({"ETag": etag}))
    if since_sig and since_sig == snapshot_sig:
        if head_only:
            return json_head_response(200, headers={"ETag": etag})
        return json_response(
            {"ok": True, "unchanged": True, "sig": snapshot_sig},
            status=200,
            headers={"ETag": etag},
        )
    if head_only:
        return json_head_response(200, headers={"ETag": etag})
    return json_response(
        payload,
        status=200,
        headers={"ETag": etag},
    )
