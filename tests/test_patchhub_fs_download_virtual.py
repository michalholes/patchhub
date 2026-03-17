# ruff: noqa: E402
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_fs import FsDownloadPayload, api_fs_download
from patchhub.asgi.asgi_app import create_app
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config
from patchhub.fs_jail import FsJail
from patchhub.models import JobRecord
from patchhub.web_jobs_db import WebJobsDatabase, load_web_jobs_db_config
from patchhub.web_jobs_virtual_fs import WebJobsVirtualFs


async def _noop_async(self) -> None:
    return None


@dataclass
class _DummyFsSelf:
    jail: FsJail
    virtual_jobs_fs: WebJobsVirtualFs


def _build_db(tmp_path: Path) -> WebJobsDatabase:
    repo_root = tmp_path / "repo"
    patches_root = repo_root / "patches"
    patches_root.mkdir(parents=True, exist_ok=True)
    cfg = load_web_jobs_db_config(repo_root, patches_root)
    return WebJobsDatabase(cfg)


def _seed_job(db: WebJobsDatabase, job_id: str = "job-514") -> None:
    db.upsert_job(
        JobRecord(
            job_id=job_id,
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
    db.append_log_line(job_id, "alpha")
    db.append_log_line(job_id, "beta")


def test_api_fs_download_handles_virtual_and_real_paths(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    _seed_job(db)
    repo_root = tmp_path / "repo"
    jail = FsJail(
        repo_root=repo_root,
        patches_root_rel="patches",
        crud_allowlist=[""],
        allow_crud=False,
    )
    self_obj = _DummyFsSelf(
        jail=jail,
        virtual_jobs_fs=WebJobsVirtualFs(db=db, enabled=True),
    )

    virtual = api_fs_download(self_obj, "artifacts/web_jobs/job-514/runner.log")
    assert isinstance(virtual, FsDownloadPayload)
    assert virtual.filename == "runner.log"
    assert virtual.data == b"alpha\nbeta"
    assert virtual.path is None

    real_path = repo_root / "patches" / "note.txt"
    real_path.write_text("hello", encoding="utf-8")
    real = api_fs_download(self_obj, "note.txt")
    assert isinstance(real, FsDownloadPayload)
    assert real.filename == "note.txt"
    assert real.path == real_path
    assert real.data is None


def test_fs_download_route_delegates_virtual_requests_to_core_api(
    tmp_path: Path,
) -> None:
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:  # pragma: no cover
        raise AssertionError(str(exc)) from exc

    cfg = load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )
    sentinel = FsDownloadPayload(
        filename="delegated.txt",
        media_type="text/plain",
        data=b"delegated-through-app-api-fs",
    )

    with (
        patch.object(AsyncAppCore, "startup", _noop_async),
        patch.object(AsyncAppCore, "shutdown", _noop_async),
        patch.object(AsyncAppCore, "api_fs_download", return_value=sentinel),
    ):
        app = create_app(repo_root=tmp_path, cfg=cfg)
        with TestClient(app) as client:
            resp = client.get(
                "/api/fs/download",
                params={"path": "artifacts/web_jobs/job-514/runner.log"},
            )

    assert resp.status_code == 200
    assert resp.content == b"delegated-through-app-api-fs"
    assert "delegated.txt" in resp.headers["content-disposition"]
