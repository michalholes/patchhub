# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.config import load_config
from patchhub.models import JobRecord


@contextmanager
def _background_loop() -> object:
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    stopped = threading.Event()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()
            stopped.set()

    thread = threading.Thread(target=_runner, name="patchhub_test_loop", daemon=True)
    thread.start()
    if not ready.wait(timeout=2.0):
        raise AssertionError("background loop did not start")
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2.0)
        if not stopped.is_set():
            raise AssertionError("background loop did not stop")


def test_db_primary_log_tail_endpoint_reads_from_sqlite_without_runner_log_file(
    tmp_path: Path,
) -> None:
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # pragma: no cover
        raise AssertionError(str(exc)) from exc

    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    app = create_app(repo_root=tmp_path, cfg=cfg)
    with TestClient(app) as client:
        db = app.state.core.web_jobs_db
        assert db is not None
        db.upsert_job(
            JobRecord(
                job_id="job-514-log",
                created_utc="2026-03-09T10:00:00Z",
                mode="patch",
                issue_id="514",
                commit_summary="DB primary",
                patch_basename="issue_514.zip",
                raw_command="python3 scripts/am_patch.py 514",
                canonical_command=["python3", "scripts/am_patch.py", "514"],
                status="success",
            )
        )
        db.append_log_line("job-514-log", "alpha")
        db.append_log_line("job-514-log", "beta")
        resp = client.get("/api/jobs/job-514-log/log_tail", params={"lines": 1})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "job_id": "job-514-log", "tail": "beta"}


def test_db_primary_jobs_routes_survive_queue_bound_to_foreign_running_loop(
    tmp_path: Path,
) -> None:
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # pragma: no cover
        raise AssertionError(str(exc)) from exc

    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    app = create_app(repo_root=tmp_path, cfg=cfg)
    with TestClient(app) as client:
        db = app.state.core.web_jobs_db
        assert db is not None
        db.upsert_job(
            JobRecord(
                job_id="job-514-cross-loop",
                created_utc="2026-03-10T00:00:00Z",
                mode="patch",
                issue_id="514",
                commit_summary="Cross-loop log tail",
                patch_basename="issue_514.zip",
                raw_command="python3 scripts/am_patch.py 514",
                canonical_command=["python3", "scripts/am_patch.py", "514"],
                status="success",
            )
        )
        db.append_log_line("job-514-cross-loop", "done")

        with _background_loop() as loop:
            future = asyncio.run_coroutine_threadsafe(app.state.core.queue.list_jobs(), loop)
            assert future.result(timeout=2.0) == []

            rescan_resp = client.post("/api/debug/indexer/force_rescan")
            assert rescan_resp.status_code == 200
            deadline = time.monotonic() + 2.0
            jobs_resp = client.get("/api/jobs")
            while time.monotonic() < deadline:
                jobs_body = jobs_resp.json()
                if [job["job_id"] for job in jobs_body.get("jobs", [])] == ["job-514-cross-loop"]:
                    break
                time.sleep(0.05)
                jobs_resp = client.get("/api/jobs")
            tail_resp = client.get(
                "/api/jobs/job-514-cross-loop/log_tail",
                params={"lines": 1},
            )

    assert jobs_resp.status_code == 200
    jobs_body = jobs_resp.json()
    assert jobs_body["ok"] is True
    assert [job["job_id"] for job in jobs_body["jobs"]] == ["job-514-cross-loop"]

    assert tail_resp.status_code == 200
    assert tail_resp.json() == {
        "ok": True,
        "job_id": "job-514-cross-loop",
        "tail": "done",
    }
