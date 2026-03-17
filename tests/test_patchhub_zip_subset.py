from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from scripts.patchhub.app_api_jobs import api_jobs_enqueue, api_patch_zip_manifest
from scripts.patchhub.config import (
    AppConfig,
    AutofillConfig,
    IndexingConfig,
    IssueConfig,
    MetaConfig,
    PathsConfig,
    RunnerConfig,
    ServerConfig,
    UiConfig,
    UploadConfig,
)
from scripts.patchhub.fs_jail import FsJail
from scripts.patchhub.run_applied_files import collect_job_applied_files


def _make_pm_zip(
    path: Path,
    *,
    commit: str = "Subset test",
    issue: str = "506",
    patch_entries: list[str],
    target: str | None = None,
) -> None:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        zf.writestr("COMMIT_MESSAGE.txt", (commit + "\n").encode("ascii"))
        zf.writestr("ISSUE_NUMBER.txt", (issue + "\n").encode("ascii"))
        if target is not None:
            zf.writestr("target.txt", (target + "\n").encode("ascii"))
        for name in patch_entries:
            zf.writestr(name, b"--- a/x\n+++ b/x\n")
    path.write_bytes(bio.getvalue())


def _cfg() -> AppConfig:
    return AppConfig(
        server=ServerConfig(host="127.0.0.1", port=1),
        meta=MetaConfig(version="test"),
        runner=RunnerConfig(
            command=["python3", "scripts/am_patch.py"],
            default_verbosity="normal",
            queue_enabled=False,
            runner_config_toml="scripts/am_patch/am_patch.toml",
        ),
        paths=PathsConfig(
            patches_root="patches",
            upload_dir="patches/incoming",
            allow_crud=False,
            crud_allowlist=[""],
        ),
        upload=UploadConfig(
            max_bytes=10_000_000,
            allowed_extensions=[".zip"],
            ascii_only_names=True,
        ),
        issue=IssueConfig(
            default_regex="issue_(\\d+)", allocation_start=1, allocation_max=999
        ),
        indexing=IndexingConfig(log_filename_regex="x", stats_windows_days=[7]),
        ui=UiConfig(base_font_px=24, drop_overlay_enabled=False),
        autofill=AutofillConfig(
            enabled=True,
            poll_interval_seconds=10,
            scan_dir="patches",
            scan_extensions=[".zip"],
            scan_ignore_filenames=[],
            scan_ignore_prefixes=[],
            choose_strategy="mtime_ns",
            tiebreaker="lex_name",
            derive_enabled=True,
            issue_regex="^issue_(\\d+)_",
            commit_regex="^issue_\\d+_(.+)\\.zip$",
            commit_replace_underscores=True,
            commit_replace_dashes=True,
            commit_collapse_spaces=True,
            commit_trim=True,
            commit_ascii_only=True,
            issue_default_if_no_match="",
            commit_default_if_no_match="",
            overwrite_policy="if_not_dirty",
            fill_patch_path=True,
            fill_issue_id=True,
            fill_commit_message=True,
            zip_commit_enabled=True,
            zip_commit_filename="COMMIT_MESSAGE.txt",
            zip_commit_max_bytes=4096,
            zip_commit_max_ratio=200,
            zip_issue_enabled=True,
            zip_issue_filename="ISSUE_NUMBER.txt",
            zip_issue_max_bytes=128,
            zip_issue_max_ratio=200,
        ),
    )


@dataclass
class _QueueDummy:
    last_job: Any | None = None

    def enqueue(self, job: Any) -> None:
        self.last_job = job

    def list_jobs(self) -> list[Any]:
        return []

    def get_job(self, _job_id: str) -> None:
        return None


@dataclass
class _SelfDummy:
    repo_root: Path
    cfg: AppConfig
    jail: FsJail
    patches_root: Path
    jobs_root: Path
    queue: _QueueDummy


def _mk_self(tmp_path: Path) -> _SelfDummy:
    cfg = _cfg()
    jail = FsJail(
        repo_root=tmp_path,
        patches_root_rel=cfg.paths.patches_root,
        crud_allowlist=cfg.paths.crud_allowlist,
        allow_crud=cfg.paths.allow_crud,
    )
    patches_root = jail.patches_root()
    patches_root.mkdir(parents=True, exist_ok=True)
    jobs_root = patches_root / "artifacts" / "web_jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    return _SelfDummy(
        repo_root=tmp_path,
        cfg=cfg,
        jail=jail,
        patches_root=patches_root,
        jobs_root=jobs_root,
        queue=_QueueDummy(),
    )


def test_api_patch_zip_manifest_reports_pm_entries(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "issue_506_demo.zip"
    _make_pm_zip(
        zpath,
        patch_entries=[
            "patches/per_file/scripts__patchhub__app_api_jobs.py.patch",
            "patches/per_file/scripts__patchhub__models.py.patch",
        ],
    )

    status, raw = api_patch_zip_manifest(s, {"path": "issue_506_demo.zip"})
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    manifest = payload["manifest"]
    assert manifest["selectable"] is True
    assert manifest["patch_entry_count"] == 2
    assert manifest["entries"][0]["repo_path"] == "scripts/patchhub/app_api_jobs.py"


def test_api_jobs_enqueue_subset_creates_derived_zip_and_provenance(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "issue_506_demo.zip"
    entries = [
        "patches/per_file/scripts__patchhub__app_api_jobs.py.patch",
        "patches/per_file/scripts__patchhub__models.py.patch",
    ]
    _make_pm_zip(zpath, patch_entries=entries)

    body = {
        "mode": "patch",
        "issue_id": "506",
        "commit_message": "Subset test",
        "patch_path": "issue_506_demo.zip",
        "selected_patch_entries": [entries[1]],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    job = payload["job"]
    assert job["original_patch_path"] == "issue_506_demo.zip"
    assert job["effective_patch_kind"] == "derived_subset"
    assert job["effective_patch_path"].startswith("patches/")
    assert job["selected_patch_entries"] == [entries[1]]
    assert job["selected_repo_paths"] == ["scripts/patchhub/models.py"]

    queued = s.queue.last_job
    assert queued is not None
    assert queued.effective_patch_kind == "derived_subset"
    derived_path = s.repo_root / job["effective_patch_path"]
    assert derived_path.exists()

    with ZipFile(derived_path, "r") as zf:
        names = sorted(zf.namelist())
    assert names == [
        "COMMIT_MESSAGE.txt",
        "ISSUE_NUMBER.txt",
        "patches/per_file/scripts__patchhub__models.py.patch",
    ]


def test_api_jobs_enqueue_rejects_raw_command_with_selected_patch_entries(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "issue_506_demo.zip"
    entry = "patches/per_file/scripts__patchhub__app_api_jobs.py.patch"
    _make_pm_zip(zpath, patch_entries=[entry])

    body = {
        "mode": "patch",
        "issue_id": "506",
        "commit_message": "Subset test",
        "patch_path": "issue_506_demo.zip",
        "raw_command": 'python3 scripts/am_patch.py 506 "Subset test" patches/issue_506_demo.zip',
        "selected_patch_entries": [entry],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert "raw_command" in payload["error"]


def test_collect_job_applied_files_prefers_logged_job_diff_manifest(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    jobs_root = patches_root / "artifacts" / "web_jobs"
    job_root = jobs_root / "j1"
    job_root.mkdir(parents=True, exist_ok=True)
    artifacts_root = patches_root / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    exact_diff = artifacts_root / "issue_506_diff.zip"
    with ZipFile(exact_diff, "w") as zf:
        zf.writestr(
            "manifest.txt",
            "FILE scripts/patchhub/app_api_jobs.py\n",
        )

    newer_diff = artifacts_root / "issue_506_diff_v2.zip"
    with ZipFile(newer_diff, "w") as zf:
        zf.writestr(
            "manifest.txt",
            "FILE scripts/patchhub/models.py\n",
        )

    (job_root / "runner.log").write_text(
        "issue_diff_zip=patches/artifacts/issue_506_diff.zip\n",
        encoding="utf-8",
    )

    job = type("Job", (), {"status": "success", "issue_id": "506", "job_id": "j1"})()
    files, source = collect_job_applied_files(
        patches_root=patches_root,
        jobs_root=jobs_root,
        job=job,
    )
    assert files == ["scripts/patchhub/app_api_jobs.py"]
    assert source == "diff_manifest"


def test_api_jobs_enqueue_subset_preserves_target_metadata(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "issue_506_demo.zip"
    entries = [
        "patches/per_file/scripts__patchhub__app_api_jobs.py.patch",
        "patches/per_file/scripts__patchhub__models.py.patch",
    ]
    _make_pm_zip(zpath, patch_entries=entries, target="../patchhub")

    body = {
        "mode": "patch",
        "issue_id": "506",
        "commit_message": "Subset test",
        "patch_path": "issue_506_demo.zip",
        "selected_patch_entries": [entries[0]],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    derived_path = s.repo_root / payload["job"]["effective_patch_path"]

    with ZipFile(derived_path, "r") as zf:
        names = sorted(zf.namelist())
        assert "target.txt" in names
        assert zf.read("target.txt") == b"../patchhub\n"
