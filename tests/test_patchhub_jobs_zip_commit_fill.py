from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from scripts.patchhub.app_api_jobs import _job_detail_json, api_jobs_enqueue
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


def _write_runner_config(
    repo_root: Path,
    *,
    target_repo_roots: list[str] | None = None,
) -> None:
    path = repo_root / "scripts" / "am_patch" / "am_patch.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_values = target_repo_roots or [
        "audiomason2=../audiomason2",
        "/home/pi/patchhub",
    ]
    rendered = ", ".join(json.dumps(value) for value in raw_values)
    path.write_text(
        f"[paths]\ntarget_repo_roots = [{rendered}]\n",
        encoding="utf-8",
    )


def _make_zip(
    path: Path,
    commit: str,
    issue: str | None = None,
    target: str | None = None,
) -> None:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        zf.writestr("COMMIT_MESSAGE.txt", (commit + "\n").encode("ascii"))
        if issue is not None:
            zf.writestr("ISSUE_NUMBER.txt", (issue + "\n").encode("ascii"))
        if target is not None:
            zf.writestr("target.txt", (target + "\n").encode("ascii"))
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
        issue=IssueConfig(default_regex="issue_(\\d+)", allocation_start=1, allocation_max=9),
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


def _mk_self(
    tmp_path: Path,
    *,
    target_repo_roots: list[str] | None = None,
) -> _SelfDummy:
    _write_runner_config(tmp_path, target_repo_roots=target_repo_roots)
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


def test_enqueue_raw_command_rejects_invalid_target_repo(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "patch",
        "raw_command": 'python3 scripts/am_patch.py 1 "x" patches/x.zip --target-repo-name bogus',
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert "target_repo" in payload["error"]


def test_enqueue_rejects_duplicate_root_binding_registry(tmp_path: Path) -> None:
    s = _mk_self(
        tmp_path,
        target_repo_roots=[
            "patchhub=.",
            "audiomason2=.",
        ],
    )

    body = {
        "mode": "patch",
        "raw_command": (
            'python3 scripts/am_patch.py 1 "x" patches/x.zip --target-repo-name patchhub'
        ),
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert "duplicate target_repo_roots root" in payload["error"]


def test_enqueue_raw_command_rejects_patch_to_finalize_live_mode_mismatch(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "patch",
        "raw_command": 'python3 scripts/am_patch.py -f "Finalize"',
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert payload["error"] == "raw_command mode does not match mode"


def test_enqueue_raw_command_rejects_workspace_to_patch_mode_mismatch(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)

    body = {
        "mode": "finalize_workspace",
        "raw_command": 'python3 scripts/am_patch.py 12 "Ship" patches/x.zip',
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert payload["error"] == "raw_command mode does not match mode"


def test_enqueue_patch_persists_commit_and_target_metadata(tmp_path: Path) -> None:
    s = _mk_self(
        tmp_path,
        target_repo_roots=["patchhub=../patchhub", "audiomason2=../audiomason2"],
    )
    zpath = s.patches_root / "issue_361_v1.zip"
    _make_zip(zpath, "Persisted commit", issue="361", target="patchhub")

    body = {
        "mode": "patch",
        "issue_id": "361",
        "commit_message": "Persisted commit",
        "patch_path": "issue_361_v1.zip",
        "target_repo": "audiomason2",
    }
    status, raw = api_jobs_enqueue(s, body)
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))["job"]
    assert payload["commit_message"] == "Persisted commit"
    assert payload["zip_target_repo"] == "patchhub"
    assert payload["selected_target_repo"] == "audiomason2"
    assert payload["effective_runner_target_repo"] == "audiomason2"
    assert payload["target_mismatch"] is True


def test_job_detail_does_not_backfill_effective_target_for_revert_gating(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    job = __import__("scripts.patchhub.models", fromlist=["JobRecord"]).JobRecord(
        job_id="job-380-detail-no-fallback",
        created_utc="2026-03-20T10:00:00Z",
        mode="patch",
        issue_id="380",
        commit_summary="Persisted summary",
        patch_basename="issue_380_v1.zip",
        raw_command="",
        canonical_command=[
            "python3",
            "scripts/am_patch.py",
            "380",
            "Fallback commit",
            "issue_380_v1.zip",
            "--target-repo-name",
            "fallback-target",
        ],
        run_start_sha="aaa111",
        run_end_sha="bbb222",
    )
    payload = _job_detail_json(s, job)
    assert payload["run_start_sha"] == "aaa111"
    assert payload["run_end_sha"] == "bbb222"
    assert payload.get("effective_runner_target_repo") is None


def test_job_detail_prefers_persisted_first_class_values(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    zpath = s.patches_root / "issue_361_v1.zip"
    _make_zip(zpath, "Zip commit", issue="361", target="zip-target")

    job = s.queue.last_job = None
    job = __import__("scripts.patchhub.models", fromlist=["JobRecord"]).JobRecord(
        job_id="job-361",
        created_utc="2026-03-20T10:00:00Z",
        mode="patch",
        issue_id="361",
        commit_summary="Persisted summary",
        patch_basename="issue_361_v1.zip",
        raw_command="",
        canonical_command=[
            "python3",
            "scripts/am_patch.py",
            "361",
            "Fallback commit",
            "issue_361_v1.zip",
            "--target-repo-name",
            "fallback-target",
        ],
        commit_message="Persisted commit",
        effective_patch_path="issue_361_v1.zip",
        zip_target_repo="persisted-zip",
        selected_target_repo="persisted-selected",
        effective_runner_target_repo="persisted-effective",
        target_mismatch=False,
    )
    payload = _job_detail_json(s, job)
    assert payload["commit_message"] == "Persisted commit"
    assert payload["zip_target_repo"] == "persisted-zip"
    assert payload["selected_target_repo"] == "persisted-selected"
    assert payload["effective_runner_target_repo"] == "persisted-effective"
    assert payload["target_mismatch"] is False
