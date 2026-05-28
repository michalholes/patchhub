from __future__ import annotations

import json
from collections.abc import Sequence
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import Request
from fastapi.responses import Response

from patchhub import app_api_core as _core_api
from patchhub.app_support import canceled_runs_signature
from patchhub.indexing import iter_runs, runs_signature
from patchhub.models import JobRecord, job_to_list_item_json, workspace_to_list_item_json
from patchhub.patch_inventory import build_patch_inventory
from patchhub.web_jobs_db import WebJobsDatabase
from patchhub.web_jobs_legacy_fs import (
    legacy_jobs_signature,
    list_legacy_job_jsons,
)
from patchhub.workspace_inventory import list_workspaces

from .async_jobs_runs_indexer import build_header_sig, build_header_summary
from .async_offload import to_thread
from .json_contract import json_head_response, json_headers, json_response
from .operator_info_runtime import build_operator_info_sig, load_operator_info

if TYPE_CHECKING:
    from .async_app_core import AsyncAppCore


def _etag_quote(token: str) -> str:
    token = str(token or "")
    return '"' + token.replace('"', "") + '"'


def _etag_matches(if_none_match: str | None, etag_value: str) -> bool:
    if if_none_match is None:
        return False
    return str(if_none_match).strip() == etag_value


def _legacy_jobs_root(core: AsyncAppCore) -> Path:
    return core.jobs_root


def _job_id_key(record: JobRecord) -> str:
    return str(record.job_id)


def _job_created_key(record: JobRecord) -> str:
    return str(record.created_utc or "")


def _get_attr_object(obj: object, name: str) -> object | None:
    try:
        return cast(object, object.__getattribute__(obj, name))
    except AttributeError:
        return None


def _jobs_sig(*, disk_sig: tuple[int, int], mem: Sequence[JobRecord]) -> str:
    parts: list[str] = []
    ordered = list(mem)
    ordered.sort(key=_job_id_key)
    for item in ordered:
        parts.append(
            "|".join(
                [
                    str(item.job_id),
                    str(item.status),
                    str(item.issue_id),
                    str(item.started_utc),
                    str(item.ended_utc),
                ]
            )
        )
    mem_sig = sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"


async def _legacy_snapshot_payload(core: AsyncAppCore) -> dict[str, object]:
    queued = 0
    running = 0
    try:
        qstate = await core.queue.state()
        queued = int(qstate.queued)
        running = int(qstate.running)
    except Exception:
        pass

    job_source_raw = _get_attr_object(core, "web_jobs_db")
    job_source = job_source_raw if isinstance(job_source_raw, WebJobsDatabase) else None
    if isinstance(job_source, WebJobsDatabase):
        disk_sig = await to_thread(job_source.jobs_signature)
    else:
        jobs_root = _legacy_jobs_root(core)
        disk_sig = await to_thread(legacy_jobs_signature, jobs_root)
    mem = await core.queue.list_jobs()
    mem_by_id = {str(j.job_id): j for j in mem}
    jobs_sig = _jobs_sig(disk_sig=disk_sig, mem=mem)

    def _load_disk_jobs_sync() -> list[JobRecord]:
        if isinstance(job_source, WebJobsDatabase):
            disk_raw = job_source.list_job_jsons(limit=200)
        else:
            jobs_root = _legacy_jobs_root(core)
            disk_raw = list_legacy_job_jsons(jobs_root, limit=200)
        disk_jobs: list[JobRecord] = []
        for item in disk_raw:
            jid = str(item.get("job_id", ""))
            if not jid or jid in mem_by_id:
                continue
            try:
                job = JobRecord.from_json(item)
            except Exception:
                continue
            disk_jobs.append(job)
        return disk_jobs

    disk_jobs = await to_thread(_load_disk_jobs_sync)
    jobs = list(mem) + disk_jobs
    jobs.sort(key=_job_created_key, reverse=True)
    jobs_items = [job_to_list_item_json(job) for job in jobs]

    base_sig = await to_thread(
        runs_signature,
        core.patches_root,
        core.cfg.indexing.log_filename_regex,
    )
    canceled_source: WebJobsDatabase | Path = (
        job_source if isinstance(job_source, WebJobsDatabase) else _legacy_jobs_root(core)
    )
    canceled_sig = await to_thread(canceled_runs_signature, canceled_source)
    runs_sig = (
        f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}:c={canceled_sig[0]}:{canceled_sig[1]}"
    )

    if TYPE_CHECKING:
        runs_status, runs_bytes = _core_api.api_runs(core, {"limit": "80"})
    else:
        runs_status, runs_bytes = await to_thread(core.api_runs, {"limit": "80"})
    runs_items: list[object] = []
    if runs_status == 200:
        try:
            loaded = cast(object, json.loads(runs_bytes.decode("utf-8")))
            if isinstance(loaded, dict):
                runs_payload = cast(dict[str, object], loaded)
                runs_raw = runs_payload.get("runs")
                if isinstance(runs_raw, list):
                    runs_items = list(cast(list[object], runs_raw))
        except Exception:
            runs_items = []

    try:
        if TYPE_CHECKING:
            patches_sig, patches_items = build_patch_inventory(core)
        else:
            patches_sig, patches_items = await to_thread(build_patch_inventory, core)
    except Exception:
        patches_sig = "patches:" + sha1(b"").hexdigest()
        patches_items = []
    if TYPE_CHECKING:
        workspaces_sig, workspaces_raw = list_workspaces(core, mem)
    else:
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
    operator_info = await to_thread(load_operator_info, core.patches_root)
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
            "patches": patches_items,
            "workspaces": workspaces_items,
            "header": header_body,
            "operator_info": operator_info,
        },
        "sigs": {
            "jobs": jobs_sig,
            "runs": runs_sig,
            "patches": patches_sig,
            "workspaces": workspaces_sig,
            "header": header_sig,
            "operator_info": operator_info_sig,
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
            payload: dict[str, object] = {
                "ok": True,
                "seq": int(snap.seq),
                "snapshot": {
                    "jobs": list(snap.jobs_items),
                    "runs": list(snap.runs_items[:80]),
                    "patches": list(snap.patches_items),
                    "workspaces": list(snap.workspaces_items),
                    "header": dict(snap.header_body),
                    "operator_info": dict(snap.operator_info),
                },
                "sigs": {
                    "jobs": str(snap.jobs_sig),
                    "runs": str(snap.runs_sig),
                    "patches": str(snap.patches_sig),
                    "workspaces": str(snap.workspaces_sig),
                    "header": str(snap.header_sig),
                    "operator_info": str(snap.operator_info_sig),
                    "snapshot": snapshot_sig,
                },
            }
            return json_response(
                payload,
                status=200,
                headers={"ETag": etag},
            )

    payload = await _legacy_snapshot_payload(core)
    sigs_raw = payload.get("sigs")
    snapshot_sig = ""
    if isinstance(sigs_raw, dict):
        sigs_dict = cast(dict[object, object], sigs_raw)
        snapshot_sig = str(sigs_dict.get("snapshot", ""))
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


async def legacy_snapshot_payload(core: AsyncAppCore) -> dict[str, object]:
    return await _legacy_snapshot_payload(core)
