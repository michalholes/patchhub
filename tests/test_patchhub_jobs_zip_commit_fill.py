from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from scripts.patchhub.app_api_jobs import api_jobs_enqueue
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


def _make_zip(path: Path, commit: str, issue: str | None = None) -> None:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        zf.writestr("COMMIT_MESSAGE.txt", (commit + "\n").encode("ascii"))
        if issue is not None:
            zf.writestr("ISSUE_NUMBER.txt", (issue + "\n").encode("ascii"))
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
            default_regex="issue_(\\d+)", allocation_start=1, allocation_max=9
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

    def list_jobs(self) -> Any:
        return []


@dataclass
class _SelfDummy:
    repo_root: Path
    cfg: AppConfig
    jail: FsJail
    patches_root: Path
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
    return _SelfDummy(
        repo_root=tmp_path,
        cfg=cfg,
        jail=jail,
        patches_root=patches_root,
        queue=_QueueDummy(),
    )


def test_enqueue_fills_commit_from_zip_when_missing(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "x.zip"
    _make_zip(zpath, "Hello")

    body = {
        "mode": "patch",
        "issue_id": "1",
        "commit_message": "",
        "patch_path": "x.zip",
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["job"]["commit_summary"] == "Hello"


def test_enqueue_does_not_override_user_commit(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "x.zip"
    _make_zip(zpath, "ZipMsg")

    body = {
        "mode": "patch",
        "issue_id": "1",
        "commit_message": "UserMsg",
        "patch_path": "x.zip",
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["job"]["commit_summary"] == "UserMsg"


def test_enqueue_fills_issue_and_commit_from_zip_when_missing(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "x.zip"
    _make_zip(zpath, "Hello", issue="602")

    body = {
        "mode": "patch",
        "issue_id": "",
        "commit_message": "",
        "patch_path": "x.zip",
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["job"]["issue_id"] == "602"
    assert payload["job"]["commit_summary"] == "Hello"


def test_enqueue_rerun_latest_builds_issue_bound_canonical_command(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "rerun_latest",
        "issue_id": "534",
        "commit_message": "Rerun latest patch",
        "patch_path": "issue_534_v1.zip",
        "gate_argv": ["--skip-pytest", "--override", "compile_check=true"],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["job"]["canonical_command"] == [
        "python3",
        "scripts/am_patch.py",
        "534",
        "Rerun latest patch",
        "issue_534_v1.zip",
        "-l",
        "--override",
        "compile_check=true",
        "--skip-pytest",
    ]


def test_enqueue_rejects_gate_argv_with_raw_command(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "patch",
        "raw_command": 'python3 scripts/am_patch.py 1 "x" patches/x.zip',
        "gate_argv": ["--skip-ruff"],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert "gate_argv" in payload["error"]


def test_enqueue_finalize_live_accepts_gate_argv(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "finalize_live",
        "commit_message": "Finalize",
        "gate_argv": ["--skip-ruff"],
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["job"]["commit_message"] == "Finalize"
    assert payload["job"]["canonical_command"] == [
        "python3",
        "scripts/am_patch.py",
        "-f",
        "Finalize",
        "--skip-ruff",
    ]
