from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from patchhub import app_api_core as _core_api
from patchhub.models import job_to_list_item_json
from patchhub.patch_inventory import build_patch_inventory

from ..repo_snapshot_cleanup import execute_repo_snapshot_cleanup
from .async_app_core import AsyncAppCore
from .async_offload import to_thread
from .job_events_db_stream import stream_job_events_db_live
from .json_contract import (
    json_bytes_response,
    json_head_response,
    json_headers,
    json_response,
)
from .operator_info_runtime import (
    append_cleanup_recent_status,
    append_cleanup_recent_status_runtime,
    load_operator_info,
    operator_info_runtime_path,
    write_operator_info,
)
from .route_diagnostics import handle_api_debug_diagnostics
from .route_snapshot_events import handle_api_snapshot_events
from .route_ui_snapshot import _legacy_snapshot_payload, handle_api_ui_snapshot
from .route_ui_snapshot_delta import handle_api_ui_snapshot_delta
from .route_workspaces import handle_api_workspaces
from .snapshot_change_broker import SnapshotChangeBroker
from .snapshot_delta_store import SnapshotDeltaStore

UPLOAD_PATCH_FILE: Any = File(...)


def _json_bytes_response(
    status: int,
    data: bytes,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    return json_bytes_response(data, status=status, headers=headers)


def _json_response_obj(
    status: int,
    data: Any,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    return json_response(data, status=status, headers=headers)


def _not_modified_response(*, etag: str = "") -> Response:
    headers = {"ETag": etag} if etag else None
    return Response(status_code=304, headers=json_headers(headers))


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(path.name)
    return ctype or "application/octet-stream"


def _etag_quote(token: str) -> str:
    token = str(token or "")
    return '"' + token.replace('"', "") + '"'


def _etag_matches(if_none_match: str | None, etag_value: str) -> bool:
    if if_none_match is None:
        return False
    inm = str(if_none_match).strip()
    return inm == etag_value


def _head_json_response(status: int, *, etag: str = "") -> Response:
    headers = {"ETag": etag} if etag else None
    return json_head_response(status, headers=headers)


def _write_cleanup_summary_record_direct(
    patches_root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    path = operator_info_runtime_path(patches_root)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)
    return payload


def _persist_cleanup_summary_record(
    patches_root: Path,
    cleanup_summary: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    try:
        return append_cleanup_recent_status(patches_root, cleanup_summary), True
    except Exception:
        operator_info = load_operator_info(patches_root)
        cleanup_recent_status = list(operator_info.get("cleanup_recent_status") or [])
        cleanup_recent_status.append(dict(cleanup_summary))
        merged_payload = {"cleanup_recent_status": cleanup_recent_status}
        try:
            return write_operator_info(patches_root, merged_payload), True
        except Exception:
            try:
                return (
                    _write_cleanup_summary_record_direct(
                        patches_root,
                        merged_payload,
                    ),
                    True,
                )
            except Exception:
                return (
                    append_cleanup_recent_status_runtime(
                        patches_root,
                        cleanup_summary,
                    ),
                    True,
                )


async def _publish_cleanup_refresh_fallback(core: Any) -> bool:
    install_snapshot = getattr(core.indexer, "install_external_snapshot_payload", None)
    if install_snapshot is None:
        return False
    try:
        payload = await _legacy_snapshot_payload(core)
    except Exception:
        return False
    try:
        install_snapshot(payload)
        return True
    except Exception:
        return False


async def _refresh_after_cleanup(core: Any) -> bool:
    try:
        await core.indexer.force_rescan()
        return True
    except Exception:
        pass

    rebuild = getattr(core.indexer, "_rebuild", None)
    if rebuild is not None:
        try:
            await rebuild(reason="patch_success_cleanup")
            return True
        except Exception:
            pass

    return await _publish_cleanup_refresh_fallback(core)


async def run_patch_job_success_cleanup(core: Any, job: Any) -> None:
    created_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = await to_thread(
        execute_repo_snapshot_cleanup,
        patches_root=core.patches_root,
        config=core.cfg.repo_snapshot_cleanup,
        job_id=str(getattr(job, "job_id", "")),
        issue_id=str(getattr(job, "issue_id", "")),
        created_utc=created_utc,
    )
    _, persisted = await to_thread(
        _persist_cleanup_summary_record,
        core.patches_root,
        summary.to_json(),
    )
    if not persisted:
        return
    await _refresh_after_cleanup(core)


def create_app(*, repo_root: Path, cfg: Any) -> FastAPI:
    app = FastAPI()
    core = AsyncAppCore(repo_root=repo_root, cfg=cfg)
    snapshot_change_broker = SnapshotChangeBroker()
    snapshot_delta_store = SnapshotDeltaStore()

    async def _handle_patch_job_success(job: Any) -> None:
        try:
            await run_patch_job_success_cleanup(core, job)
        except Exception:
            return

    core.register_patch_success_callback(_handle_patch_job_success)

    def _publish_snapshot_change(snap: Any) -> None:
        snapshot_delta_store.record_snapshot(snap)
        snapshot_change_broker.publish(
            {
                "seq": int(getattr(snap, "seq", 0) or 0),
                "sigs": {
                    "jobs": str(snap.jobs_sig),
                    "runs": str(snap.runs_sig),
                    "patches": str(snap.patches_sig),
                    "workspaces": str(snap.workspaces_sig),
                    "header": str(snap.header_sig),
                    "operator_info": str(snap.operator_info_sig),
                    "snapshot": str(snap.snapshot_sig),
                },
            }
        )

    core.indexer.set_snapshot_change_callback(_publish_snapshot_change)
    app.state.core = core
    app.state.snapshot_change_broker = snapshot_change_broker
    app.state.snapshot_delta_store = snapshot_delta_store

    @app.on_event("startup")
    async def _startup() -> None:
        await core.startup()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        snapshot_change_broker.close()
        await core.shutdown()

    @app.get("/")
    async def index() -> HTMLResponse:
        html = core.render_index().encode("utf-8")
        return HTMLResponse(content=html, status_code=200)

    @app.get("/debug")
    async def debug() -> HTMLResponse:
        html = core.render_debug().encode("utf-8")
        return HTMLResponse(content=html, status_code=200)

    @app.get("/static/{rel_path:path}")
    async def static(rel_path: str) -> FileResponse:
        def _resolve_static_sync(rel_path: str) -> Path | None:
            base = Path(__file__).resolve().parent.parent / "static"
            p = (base / rel_path).resolve()
            if base not in p.parents:
                return None
            if not p.exists() or not p.is_file():
                return None
            return p

        p = await to_thread(_resolve_static_sync, rel_path)
        if p is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(p, media_type=_guess_content_type(p))

    @app.get("/api/config")
    async def api_config() -> Response:
        status, data = await to_thread(core.api_config)
        return _json_bytes_response(status, data)

    @app.get("/api/amp/schema")
    async def api_amp_schema() -> Response:
        status, data = await to_thread(core.api_amp_schema)
        return _json_bytes_response(status, data)

    @app.get("/api/amp/config")
    async def api_amp_config_get() -> Response:
        status, data = await to_thread(core.api_amp_config_get)
        return _json_bytes_response(status, data)

    @app.post("/api/amp/config")
    async def api_amp_config_post(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_amp_config_post, body)
        return _json_bytes_response(status, data)

    @app.get("/api/fs/list")
    async def api_fs_list(path: str = "") -> Response:
        status, data = await to_thread(core.api_fs_list, path)
        return _json_bytes_response(status, data)

    @app.get("/api/fs/stat")
    async def api_fs_stat(path: str = "") -> Response:
        status, data = await to_thread(core.api_fs_stat, path)
        return _json_bytes_response(status, data)

    @app.get("/api/workspaces")
    async def api_workspaces(request: Request) -> Response:
        return await handle_api_workspaces(core, request)

    @app.get("/api/patches/latest")
    async def api_patches_latest(request: Request) -> Response:
        qs = dict(request.query_params)
        status, data = await to_thread(core.api_patches_latest, qs)
        etag = ""
        try:
            obj = json.loads(data.decode("utf-8"))
            token = str(obj.get("token", ""))
            if token:
                etag = _etag_quote(token)
        except Exception:
            etag = ""

        inm = request.headers.get("if-none-match")
        if status == 200 and etag and _etag_matches(inm, etag):
            return _not_modified_response(etag=etag)
        headers = {"ETag": etag} if (status == 200 and etag) else None
        return _json_bytes_response(status, data, headers=headers)

    @app.get("/api/patches/inventory")
    async def api_patches_inventory(request: Request) -> Response:
        since_sig = str(request.query_params.get("since_sig", "")).strip()
        sig, items = await to_thread(build_patch_inventory, core)
        etag = _etag_quote(sig)
        inm = request.headers.get("if-none-match")
        if etag and _etag_matches(inm, etag):
            return _not_modified_response(etag=etag)
        if since_sig and since_sig == sig:
            return _json_response_obj(
                200,
                {"ok": True, "unchanged": True, "sig": sig},
                headers={"ETag": etag},
            )
        return _json_response_obj(
            200,
            {"ok": True, "items": items, "sig": sig},
            headers={"ETag": etag},
        )

    @app.get("/api/fs/read_text")
    async def api_fs_read_text(request: Request) -> Response:
        qs = dict(request.query_params)
        status, data = await to_thread(core.api_fs_read_text, qs)
        return _json_bytes_response(status, data)

    @app.get("/api/fs/download")
    async def api_fs_download(path: str = "") -> Response:
        result = await to_thread(core.api_fs_download, path)
        if isinstance(result, tuple):
            status, data = result
            return _json_bytes_response(status, data)
        headers = {"Content-Disposition": f'attachment; filename="{result.filename}"'}
        if result.path is not None:
            return FileResponse(
                result.path,
                media_type=result.media_type,
                filename=result.filename,
                headers=headers,
            )
        return Response(
            content=result.data or b"",
            media_type=result.media_type,
            headers=headers,
        )

    @app.get("/api/runs")
    async def api_runs(request: Request) -> Response:
        qs = dict(request.query_params)
        issue_id_s = str(qs.get("issue_id", "")).strip()
        result = str(qs.get("result", "")).strip()
        since_sig = str(qs.get("since_sig", "")).strip()

        if core.indexer.ready():
            got = core.indexer.get_runs()
            if got is not None:
                sig, runs_items = got
                etag = _etag_quote(sig)

                # ETag/304 is canonical only for default (unfiltered) list.
                if not issue_id_s and not result:
                    inm = request.headers.get("if-none-match")
                    if etag and _etag_matches(inm, etag):
                        return _not_modified_response(etag=etag)
                    if since_sig and since_sig == sig:
                        return _json_response_obj(
                            200,
                            {"ok": True, "unchanged": True, "sig": sig},
                            headers={"ETag": etag},
                        )

                limit = int(qs.get("limit", "100"))
                limit = max(1, min(limit, 500))

                if issue_id_s:
                    try:
                        iid = int(issue_id_s)
                    except ValueError:
                        return _json_response_obj(
                            400,
                            {"ok": False, "error": "Invalid issue_id"},
                        )
                    runs_items = [r for r in runs_items if int(r.get("issue_id", 0) or 0) == iid]

                if result:
                    if result not in ("success", "fail", "unknown", "canceled"):
                        return _json_response_obj(
                            400,
                            {"ok": False, "error": "Invalid result filter"},
                        )
                    runs_items = [r for r in runs_items if str(r.get("result", "")) == result]

                runs_items = runs_items[:limit]
                headers = {"ETag": etag} if (not issue_id_s and not result and etag) else None
                return _json_response_obj(
                    200,
                    {"ok": True, "runs": runs_items, "sig": sig},
                    headers=headers,
                )

        # Legacy path (indexer not ready / error).
        # ETag/304 is canonical only for default (unfiltered) list.
        etag = ""
        if not issue_id_s and not result:
            from patchhub.app_support import canceled_runs_signature
            from patchhub.indexing import runs_signature

            base_sig = await to_thread(
                runs_signature, core.patches_root, core.cfg.indexing.log_filename_regex
            )
            canceled_source = core.web_jobs_db if core.web_jobs_db is not None else core.jobs_root
            canceled_sig = await to_thread(canceled_runs_signature, canceled_source)
            sig = (
                f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}"
                f":c={canceled_sig[0]}:{canceled_sig[1]}"
            )
            etag = _etag_quote(sig)
            inm = request.headers.get("if-none-match")
            if etag and _etag_matches(inm, etag):
                return _not_modified_response(etag=etag)
            if since_sig and since_sig == sig:
                return _json_response_obj(
                    200,
                    {"ok": True, "unchanged": True, "sig": sig},
                    headers={"ETag": etag},
                )

        status, data = await to_thread(core.api_runs, qs)
        headers = {"ETag": etag} if (status == 200 and etag) else None
        return _json_bytes_response(status, data, headers=headers)

    @app.head("/api/runs")
    async def api_runs_head(request: Request) -> Response:
        qs = dict(request.query_params)
        issue_id_s = str(qs.get("issue_id", "")).strip()
        result = str(qs.get("result", "")).strip()
        since_sig = str(qs.get("since_sig", "")).strip()

        if issue_id_s or result:
            return _head_json_response(200)

        if core.indexer.ready():
            got = core.indexer.get_runs()
            if got is not None:
                sig, _runs_items = got
                etag = _etag_quote(sig)

                inm = request.headers.get("if-none-match")
                if etag and _etag_matches(inm, etag):
                    return _not_modified_response(etag=etag)
                if since_sig and since_sig == sig:
                    return _head_json_response(200, etag=etag)
                return _head_json_response(200, etag=etag)

        from patchhub.app_support import canceled_runs_signature
        from patchhub.indexing import runs_signature

        base_sig = await to_thread(
            runs_signature,
            core.patches_root,
            core.cfg.indexing.log_filename_regex,
        )
        canceled_source = core.web_jobs_db if core.web_jobs_db is not None else core.jobs_root
        canceled_sig = await to_thread(canceled_runs_signature, canceled_source)
        sig = (
            f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}"
            f":c={canceled_sig[0]}:{canceled_sig[1]}"
        )
        etag = _etag_quote(sig)

        inm = request.headers.get("if-none-match")
        if etag and _etag_matches(inm, etag):
            return _not_modified_response(etag=etag)
        if since_sig and since_sig == sig:
            return _head_json_response(200, etag=etag)
        return _head_json_response(200, etag=etag)

    @app.get("/api/runs/{issue_id}")
    async def api_runs_get(issue_id: int) -> Response:
        status, data = await to_thread(_core_api.api_run_detail, core, int(issue_id))
        return _json_bytes_response(status, data)

    @app.get("/api/runner/tail")
    async def api_runner_tail(request: Request) -> Response:
        qs = dict(request.query_params)
        status, data = await to_thread(core.api_runner_tail, qs)
        return _json_bytes_response(status, data)

    @app.get("/api/jobs")
    async def api_jobs_list(request: Request) -> Response:
        since_sig = str(request.query_params.get("since_sig", "")).strip()

        if core.indexer.ready():
            got = core.indexer.get_jobs()
            if got is not None:
                sig, jobs_items = got
                etag = _etag_quote(sig)
                inm = request.headers.get("if-none-match")
                if etag and _etag_matches(inm, etag):
                    return _not_modified_response(etag=etag)
                if since_sig and since_sig == sig:
                    return _json_response_obj(
                        200,
                        {"ok": True, "unchanged": True, "sig": sig},
                        headers={"ETag": etag},
                    )
                return _json_response_obj(
                    200,
                    {"ok": True, "jobs": jobs_items, "sig": sig},
                    headers={"ETag": etag},
                )

        # Legacy path (indexer not ready / error).
        mem = await core.queue.list_jobs()
        mem_by_id = {j.job_id: j for j in mem}

        from hashlib import sha1

        disk_sig = await to_thread(core.jobs_signature_sync)
        mem_parts: list[str] = []
        for j in sorted(mem, key=lambda x: str(getattr(x, "job_id", ""))):
            jid = str(getattr(j, "job_id", ""))
            st = str(getattr(j, "status", ""))
            isu = str(getattr(j, "issue_id", ""))
            su = str(getattr(j, "started_utc", ""))
            eu = str(getattr(j, "ended_utc", ""))
            mem_parts.append("|".join([jid, st, isu, su, eu]))
        mem_sig = sha1("\n".join(mem_parts).encode("utf-8")).hexdigest()
        sig = f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"
        etag = _etag_quote(sig)
        inm = request.headers.get("if-none-match")
        if etag and _etag_matches(inm, etag):
            return _not_modified_response(etag=etag)
        if since_sig and since_sig == sig:
            return _json_response_obj(
                200,
                {"ok": True, "unchanged": True, "sig": sig},
                headers={"ETag": etag},
            )

        # Build payload only when changed.

        def _load_disk_jobs_sync(mem_by_id: dict[str, object]) -> list[Any]:
            from datetime import UTC, datetime

            disk_raw = core.list_job_jsons_sync(limit=200)
            disk: list[Any] = []
            for r in disk_raw:
                jid = str(r.get("job_id", ""))
                if not jid or jid in mem_by_id:
                    continue
                j = core._load_job_from_disk(jid)
                if j is None:
                    continue

                status = str(getattr(j, "status", ""))
                if status in ("queued", "running"):
                    j.status = "fail"
                    j.ended_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    j.error = "orphaned: not in memory queue"
                    core.mark_orphaned_sync(jid)

                disk.append(j)
            return disk

        disk = await to_thread(_load_disk_jobs_sync, mem_by_id)

        jobs = mem + disk
        jobs.sort(key=lambda j: str(j.created_utc or ""), reverse=True)
        return _json_response_obj(
            200,
            {"ok": True, "jobs": [job_to_list_item_json(j) for j in jobs], "sig": sig},
            headers={"ETag": etag},
        )

    @app.head("/api/jobs")
    async def api_jobs_list_head(request: Request) -> Response:
        since_sig = str(request.query_params.get("since_sig", "")).strip()

        if core.indexer.ready():
            got = core.indexer.get_jobs()
            if got is not None:
                sig, _jobs_items = got
                etag = _etag_quote(sig)

                inm = request.headers.get("if-none-match")
                if etag and _etag_matches(inm, etag):
                    return _not_modified_response(etag=etag)
                if since_sig and since_sig == sig:
                    return _head_json_response(200, etag=etag)
                return _head_json_response(200, etag=etag)

        from hashlib import sha1

        mem = await core.queue.list_jobs()
        disk_sig = await to_thread(core.jobs_signature_sync)

        mem_parts: list[str] = []
        for j in sorted(mem, key=lambda x: str(getattr(x, "job_id", ""))):
            jid = str(getattr(j, "job_id", ""))
            st = str(getattr(j, "status", ""))
            isu = str(getattr(j, "issue_id", ""))
            su = str(getattr(j, "started_utc", ""))
            eu = str(getattr(j, "ended_utc", ""))
            mem_parts.append("|".join([jid, st, isu, su, eu]))

        mem_sig = sha1("\n".join(mem_parts).encode("utf-8")).hexdigest()
        sig = f"jobs:d={disk_sig[0]}:{disk_sig[1]}:m={mem_sig}"
        etag = _etag_quote(sig)

        inm = request.headers.get("if-none-match")
        if etag and _etag_matches(inm, etag):
            return _not_modified_response(etag=etag)
        if since_sig and since_sig == sig:
            return _head_json_response(200, etag=etag)
        return _head_json_response(200, etag=etag)

    @app.get("/api/patches/zip_manifest")
    async def api_patch_zip_manifest(path: str) -> Response:
        status, data = await to_thread(core.api_patch_zip_manifest, {"path": path})
        return _json_bytes_response(status, data)

    @app.get("/api/jobs/{job_id}")
    async def api_jobs_get(job_id: str) -> Response:
        status, data = await to_thread(core.api_jobs_get, job_id)
        return _json_bytes_response(status, data)

    @app.get("/api/jobs/{job_id}/log_tail")
    async def api_jobs_log_tail(job_id: str, lines: int = 200) -> Response:
        job = await core.queue.get_job(job_id)
        if job is None:
            job = await to_thread(core._load_job_from_disk, job_id)
        if job is None:
            return _json_response_obj(404, {"ok": False, "error": "Not found"})
        tail = await to_thread(core.read_log_tail_sync, job_id, lines=lines)
        return _json_response_obj(200, {"ok": True, "job_id": job_id, "tail": tail})

    @app.post("/api/jobs/{job_id}/cancel")
    async def api_jobs_cancel(job_id: str) -> Response:
        ok = await core.queue.cancel(job_id)
        if not ok:
            return _json_response_obj(409, {"ok": False, "error": "Cannot cancel"})
        return _json_response_obj(200, {"ok": True, "job_id": job_id})

    @app.post("/api/jobs/{job_id}/hard_stop")
    async def api_jobs_hard_stop(job_id: str) -> Response:
        ok = await core.queue.hard_stop(job_id)
        if not ok:
            return _json_response_obj(409, {"ok": False, "error": "Cannot hard stop"})
        return _json_response_obj(200, {"ok": True, "job_id": job_id})

    @app.post("/api/jobs/enqueue")
    async def api_jobs_enqueue(body: dict[str, Any]) -> Response:
        from patchhub.app_api_jobs import api_jobs_enqueue

        # Reuse legacy parsing/validation logic, but enqueue via async queue.
        # The legacy helper calls self.queue.enqueue(job), which is sync.
        # We provide a small adapter object with an async enqueue.

        def _error_response(exc: Exception) -> Response:
            msg = f"enqueue_failed: {type(exc).__name__}: {exc}"
            msg = msg.encode("ascii", errors="replace").decode("ascii")
            return _json_response_obj(500, {"ok": False, "error": msg})

        class _Adapter:
            def __init__(self, core: AsyncAppCore) -> None:
                self.core = core
                self.cfg = core.cfg
                self.jail = core.jail
                self.repo_root = core.repo_root
                self.patches_root = core.patches_root
                self.jobs_root = core.jobs_root
                self.queue = self
                self._pending: list[asyncio.Task[None]] = []

            def _load_job_from_disk(self, job_id: str):
                return core._load_job_from_disk(job_id)

            def queue_block_reason(self) -> str | None:
                return core.queue_block_reason()

            async def _enqueue_async(self, job: Any) -> None:
                await core.queue.enqueue(job)

            def enqueue(self, job: Any) -> None:
                t = asyncio.get_running_loop().create_task(self._enqueue_async(job))
                self._pending.append(t)

        adapter = _Adapter(core)
        try:
            status, data = api_jobs_enqueue(adapter, body)
        except Exception as exc:
            return _error_response(exc)
        if status < 400 and adapter._pending:
            try:
                await asyncio.gather(*adapter._pending)
            except Exception as exc:
                return _error_response(exc)
        return _json_bytes_response(status, data)

    @app.post("/api/parse_command")
    async def api_parse_command(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_parse_command, body)
        return _json_bytes_response(status, data)

    @app.post("/api/upload/patch")
    async def api_upload_patch(file: UploadFile = UPLOAD_PATCH_FILE) -> Response:
        filename = os.path.basename(file.filename or "")
        data = await file.read()
        status, resp = await to_thread(core.api_upload_patch, filename, data)
        return _json_bytes_response(status, resp)

    @app.post("/api/fs/mkdir")
    async def api_fs_mkdir(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_fs_mkdir, body)
        return _json_bytes_response(status, data)

    @app.post("/api/fs/rename")
    async def api_fs_rename(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_fs_rename, body)
        return _json_bytes_response(status, data)

    @app.post("/api/fs/delete")
    async def api_fs_delete(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_fs_delete, body)
        return _json_bytes_response(status, data)

    @app.post("/api/fs/unzip")
    async def api_fs_unzip(body: dict[str, Any]) -> Response:
        status, data = await to_thread(core.api_fs_unzip, body)
        return _json_bytes_response(status, data)

    @app.post("/api/fs/archive")
    async def api_fs_archive(body: dict[str, Any]) -> Response:
        paths = body.get("paths")
        if not isinstance(paths, list) or not paths:
            return _json_response_obj(
                400,
                {"ok": False, "error": "paths must be a non-empty list"},
            )

        rel_paths: list[str] = []
        for x in paths:
            if not isinstance(x, str):
                continue
            rel = x.strip().lstrip("/")
            if rel:
                rel_paths.append(rel)
        if not rel_paths:
            return _json_response_obj(400, {"ok": False, "error": "No valid paths"})
        rel_paths = sorted(set(rel_paths))

        def _build_archive_bytes_sync(core: AsyncAppCore, rel_paths: list[str]) -> bytes:
            files: list[tuple[str, Path]] = []
            seen: set[str] = set()
            for rel in rel_paths:
                p = core.jail.resolve_rel(rel)
                if not p.exists():
                    raise FileNotFoundError(rel)
                if p.is_file():
                    if rel not in seen:
                        files.append((rel, p))
                        seen.add(rel)
                    continue

                root = p
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames.sort()
                    filenames.sort()
                    dp = Path(dirpath)
                    for fn in filenames:
                        fp = dp / fn
                        if not fp.is_file():
                            continue
                        sub_rel = str(fp.relative_to(core.jail.patches_root())).replace(os.sep, "/")
                        if sub_rel not in seen:
                            files.append((sub_rel, fp))
                            seen.add(sub_rel)

            files.sort(key=lambda t: t[0])

            import io
            import zipfile

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for arc, fp in files:
                    z.write(fp, arcname=arc.replace(os.sep, "/"))

            return buf.getvalue()

        try:
            data = await to_thread(_build_archive_bytes_sync, core, rel_paths)
        except FileNotFoundError as e:
            return _json_response_obj(400, {"ok": False, "error": f"Not found: {e.args[0]}"})
        except Exception as e:
            return _json_response_obj(400, {"ok": False, "error": str(e)})
        headers = {"Content-Disposition": 'attachment; filename="selection.zip"'}
        return Response(content=data, media_type="application/zip", headers=headers)

    @app.post("/api/debug/indexer/force_rescan")
    async def api_debug_indexer_force_rescan() -> Response:
        await core.indexer.force_rescan()
        return _json_response_obj(200, {"ok": True})

    @app.get("/api/debug/diagnostics")
    async def api_debug_diagnostics(request: Request) -> Response:
        return await handle_api_debug_diagnostics(core, request)

    @app.get("/api/ui_snapshot")
    async def api_ui_snapshot(request: Request) -> Response:
        return await handle_api_ui_snapshot(core, request)

    @app.head("/api/ui_snapshot")
    async def api_ui_snapshot_head(request: Request) -> Response:
        return await handle_api_ui_snapshot(core, request, head_only=True)

    @app.get("/api/events")
    async def api_snapshot_events() -> StreamingResponse:
        return await handle_api_snapshot_events(core, snapshot_change_broker)

    @app.get("/api/ui_snapshot_delta")
    async def api_ui_snapshot_delta(request: Request) -> Response:
        return await handle_api_ui_snapshot_delta(request, snapshot_delta_store)

    @app.get("/api/jobs/{job_id}/events")
    async def api_jobs_events(job_id: str) -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            job = await core.queue.get_job(job_id)
            disk_job = None
            if job is None:
                disk_job = await to_thread(core._load_job_from_disk, job_id)

            if job is None and disk_job is None:
                data = json.dumps({"reason": "job_not_found"}, ensure_ascii=True)
                yield f"event: end\ndata: {data}\n\n".encode()
                return

            async def job_status() -> str | None:
                j = await core.queue.get_job(job_id)
                if j is not None:
                    return str(j.status)
                if disk_job is None:
                    current = await to_thread(core._load_job_from_disk, job_id)
                else:
                    current = disk_job
                return str(current.status) if current is not None else None

            async def get_broker() -> Any:
                if job is None:
                    return None
                return await core.queue.get_broker(job_id)

            if core.web_jobs_db is not None:
                async for chunk in stream_job_events_db_live(
                    job_id=str(job_id),
                    db=core.web_jobs_db,
                    in_memory_job=job is not None,
                    job_status=job_status,
                    get_broker=get_broker,
                ):
                    yield chunk
                return

            current = job if job is not None else disk_job
            if current is None:
                data = json.dumps({"reason": "job_not_found"}, ensure_ascii=True)
                yield f"event: end\ndata: {data}\n\n".encode()
                return
            from .sse_jsonl_stream import stream_job_events_sse

            jsonl_path = core._job_jsonl_path(current)
            async for chunk in stream_job_events_sse(
                job_id=str(job_id),
                jsonl_path=jsonl_path,
                job_status=job_status,
            ):
                yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
