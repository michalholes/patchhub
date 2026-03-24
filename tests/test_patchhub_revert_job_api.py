# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.asgi_app import create_app
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config
from patchhub.models import JobRecord


async def _noop_async(self) -> None:
    return None


CFG_PATH = Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"


def _write_runner_config(repo_root: Path) -> None:
    cfg_path = repo_root / "scripts" / "am_patch" / "am_patch.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        '[paths]\ntarget_repo_roots = ["patchhub=."]\n',
        encoding="utf-8",
    )


def _write_job(jobs_root: Path, job: JobRecord) -> None:
    job_dir = jobs_root / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        json.dumps(job.to_json(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


class TestPatchhubRevertJobApi(unittest.TestCase):
    def test_revert_endpoint_enqueues_revert_job_for_source_with_required_fields(
        self,
    ) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_runner_config(root)
            cfg = load_config(CFG_PATH)
            with (
                patch.object(AsyncAppCore, "startup", _noop_async),
                patch.object(AsyncAppCore, "shutdown", _noop_async),
            ):
                app = create_app(repo_root=root, cfg=cfg)
                core = app.state.core
                core.queue_block_reason = lambda: None
                source_job = JobRecord(
                    job_id="job-source-380",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Buggy change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha="aaa111",
                    run_end_sha="bbb222",
                )
                _write_job(core.jobs_root, source_job)
                with TestClient(app) as client:
                    resp = client.post(f"/api/jobs/{source_job.job_id}/revert")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["job"]["mode"], "revert_job")
        self.assertEqual(
            payload["job"]["revert_source_job_id"],
            source_job.job_id,
        )
        self.assertEqual(payload["job"]["effective_runner_target_repo"], "patchhub")

    def test_revert_endpoint_respects_queue_block_reason(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_runner_config(root)
            cfg = load_config(CFG_PATH)
            with (
                patch.object(AsyncAppCore, "startup", _noop_async),
                patch.object(AsyncAppCore, "shutdown", _noop_async),
            ):
                app = create_app(repo_root=root, cfg=cfg)
                core = app.state.core
                core.queue_block_reason = lambda: "Backend mode selection is not finished"
                source_job = JobRecord(
                    job_id="job-source-blocked-380",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Blocked change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha="aaa111",
                    run_end_sha="bbb222",
                )
                _write_job(core.jobs_root, source_job)
                with TestClient(app) as client:
                    resp = client.post(f"/api/jobs/{source_job.job_id}/revert")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "Backend mode selection is not finished")

    def test_revert_endpoint_rejects_source_without_required_fields(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_runner_config(root)
            cfg = load_config(CFG_PATH)
            with (
                patch.object(AsyncAppCore, "startup", _noop_async),
                patch.object(AsyncAppCore, "shutdown", _noop_async),
            ):
                app = create_app(repo_root=root, cfg=cfg)
                core = app.state.core
                core.queue_block_reason = lambda: None
                source_job = JobRecord(
                    job_id="job-source-missing-380",
                    created_utc="2026-03-24T10:00:00Z",
                    mode="patch",
                    issue_id="380",
                    commit_summary="Incomplete change",
                    patch_basename="issue_380_v1.zip",
                    raw_command="python3 scripts/am_patch.py 380",
                    canonical_command=["python3", "scripts/am_patch.py", "380"],
                    status="success",
                    effective_runner_target_repo="patchhub",
                    run_start_sha="aaa111",
                )
                _write_job(core.jobs_root, source_job)
                with TestClient(app) as client:
                    resp = client.post(f"/api/jobs/{source_job.job_id}/revert")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"], "Source job is not revertable")
