# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.app_api_jobs import api_jobs_cancel, api_jobs_get, api_jobs_hard_stop
from patchhub.asgi.async_app_core import AsyncAppCore
from patchhub.config import load_config


class _QueueFalse:
    async def cancel(self, job_id: str) -> bool:
        del job_id
        return False

    async def hard_stop(self, job_id: str) -> bool:
        del job_id
        return False


@dataclass
class _LegacySelf:
    queue: Any


def _load_repo_cfg() -> Any:
    return load_config(
        Path(__file__).resolve().parents[1] / "scripts" / "patchhub" / "patchhub.toml"
    )


def test_legacy_api_jobs_cancel_returns_409_without_unawaited_warning() -> None:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        status, raw = api_jobs_cancel(_LegacySelf(queue=_QueueFalse()), "job-800")
    payload = json.loads(raw.decode("utf-8"))
    assert status == 409
    assert payload["error"] == "Cannot cancel"
    assert not any("was never awaited" in str(item.message) for item in seen)


def test_legacy_api_jobs_hard_stop_returns_409_without_unawaited_warning() -> None:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        status, raw = api_jobs_hard_stop(_LegacySelf(queue=_QueueFalse()), "job-801")
    payload = json.loads(raw.decode("utf-8"))
    assert status == 409
    assert payload["error"] == "Cannot hard stop"
    assert not any("was never awaited" in str(item.message) for item in seen)


def test_async_app_core_wires_terminate_grace_from_config(tmp_path: Path) -> None:
    cfg = _load_repo_cfg()
    core = AsyncAppCore(repo_root=tmp_path, cfg=cfg)
    assert core.queue._terminate_grace_s == cfg.runner.terminate_grace_s


class _QueueJobAsync:
    def __init__(self, job: Any) -> None:
        self._job = job

    async def get_job(self, job_id: str) -> Any:
        del job_id
        return self._job


@dataclass
class _LegacyJobsSelf:
    queue: Any
    patches_root: Path
    jobs_root: Path

    def _load_job_from_disk(self, job_id: str) -> Any:
        del job_id
        return None


def test_legacy_api_jobs_get_accepts_async_queue_get_job(tmp_path: Path) -> None:
    from patchhub.models import JobRecord

    patches_root = tmp_path / "patches"
    jobs_root = patches_root / "artifacts" / "web_jobs"
    (jobs_root / "job-901").mkdir(parents=True, exist_ok=True)
    (jobs_root / "job-901" / "runner.log").write_text(
        "FILES:\nscripts/patchhub/app_api_jobs.py\n",
        encoding="utf-8",
    )
    job = JobRecord(
        job_id="job-901",
        created_utc="2026-03-09T00:00:00Z",
        mode="patch",
        issue_id="901",
        commit_summary="Test",
        patch_basename="issue_901_v1.zip",
        raw_command="",
        canonical_command=["python3", "scripts/am_patch.py"],
        status="success",
    )
    status, raw = api_jobs_get(
        _LegacyJobsSelf(
            queue=_QueueJobAsync(job),
            patches_root=patches_root,
            jobs_root=jobs_root,
        ),
        "job-901",
    )
    payload = json.loads(raw.decode("utf-8"))
    assert status == 200
    assert payload["job"]["job_id"] == "job-901"
    assert payload["job"]["applied_files"] == ["scripts/patchhub/app_api_jobs.py"]
