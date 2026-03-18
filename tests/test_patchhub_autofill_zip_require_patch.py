from __future__ import annotations

import json
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from scripts.patchhub import app_api_core as api_core
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


def _make_zip(path: Path, members: dict[str, bytes]) -> None:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    path.write_bytes(bio.getvalue())


def _set_mtime(path: Path, seconds: int) -> None:
    os.utime(path, (seconds, seconds))


def _cfg(scan_zip_require_patch: bool) -> AppConfig:
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
            derive_enabled=False,
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
            zip_commit_enabled=False,
            zip_commit_filename="COMMIT_MESSAGE.txt",
            zip_commit_max_bytes=4096,
            zip_commit_max_ratio=200,
            zip_issue_enabled=True,
            zip_issue_filename="ISSUE_NUMBER.txt",
            zip_issue_max_bytes=128,
            zip_issue_max_ratio=200,
            scan_zip_require_patch=scan_zip_require_patch,
        ),
    )


@dataclass
class _SelfDummy:
    repo_root: Path
    cfg: AppConfig
    jail: FsJail

    _autofill_scan_dir_rel = api_core._autofill_scan_dir_rel
    _derive_from_filename = api_core._derive_from_filename


def _mk_self(tmp_path: Path, scan_zip_require_patch: bool) -> _SelfDummy:
    cfg = _cfg(scan_zip_require_patch)
    jail = FsJail(
        repo_root=tmp_path,
        patches_root_rel=cfg.paths.patches_root,
        crud_allowlist=cfg.paths.crud_allowlist,
        allow_crud=cfg.paths.allow_crud,
    )
    patches_root = jail.patches_root()
    patches_root.mkdir(parents=True, exist_ok=True)
    return _SelfDummy(repo_root=tmp_path, cfg=cfg, jail=jail)


def _status_text(payload: dict[str, Any]) -> str:
    lines = payload.get("status") or []
    return "\n".join(str(x) for x in lines)


def test_scan_zip_require_patch_false_keeps_legacy_selection(tmp_path: Path) -> None:
    s = _mk_self(tmp_path, scan_zip_require_patch=False)
    patches_root = s.jail.patches_root()

    newer_nonpatch = patches_root / "newer_nonpatch.zip"
    older_patch = patches_root / "older_patch.zip"

    _make_zip(newer_nonpatch, {"README.txt": b"x"})
    _make_zip(older_patch, {"foo/bar/x.patch": b"diff"})

    _set_mtime(older_patch, 1_000_000_000)
    _set_mtime(newer_nonpatch, 1_000_000_100)

    status, body = api_core.api_patches_latest(s)
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"]
    assert payload["found"] is True
    assert payload["filename"] == "newer_nonpatch.zip"
    assert "ignored_zip_no_patch=0" in _status_text(payload)


def test_scan_zip_require_patch_true_ignores_nonpatch_zip(tmp_path: Path) -> None:
    s = _mk_self(tmp_path, scan_zip_require_patch=True)
    patches_root = s.jail.patches_root()

    newer_nonpatch = patches_root / "newer_nonpatch.zip"
    older_patch = patches_root / "older_patch.zip"

    _make_zip(newer_nonpatch, {"README.txt": b"x"})
    _make_zip(older_patch, {"foo/bar/x.patch": b"diff"})

    _set_mtime(older_patch, 1_000_000_000)
    _set_mtime(newer_nonpatch, 1_000_000_100)

    status, body = api_core.api_patches_latest(s)
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"]
    assert payload["found"] is True
    assert payload["filename"] == "older_patch.zip"
    assert "ignored_zip_no_patch=1" in _status_text(payload)


def test_scan_zip_require_patch_true_all_nonpatch_returns_not_found(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path, scan_zip_require_patch=True)
    patches_root = s.jail.patches_root()

    a = patches_root / "a.zip"
    b = patches_root / "b.zip"

    _make_zip(a, {"README.txt": b"x"})
    _make_zip(b, {"notes.md": b"y"})

    _set_mtime(a, 1_000_000_000)
    _set_mtime(b, 1_000_000_100)

    status, body = api_core.api_patches_latest(s)
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"]
    assert payload["found"] is False
    st = _status_text(payload)
    assert "selected=none" in st
    assert "ignored_zip_no_patch=2" in st


def test_scan_zip_require_patch_true_corrupted_zip_is_ignored(tmp_path: Path) -> None:
    s = _mk_self(tmp_path, scan_zip_require_patch=True)
    patches_root = s.jail.patches_root()

    corrupted = patches_root / "corrupted.zip"
    valid_patch = patches_root / "valid_patch.zip"

    corrupted.write_text("not a zip", encoding="ascii")
    _make_zip(valid_patch, {"x.patch": b"diff"})

    _set_mtime(valid_patch, 1_000_000_000)
    _set_mtime(corrupted, 1_000_000_100)

    status, body = api_core.api_patches_latest(s)
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"]
    assert payload["found"] is True
    assert payload["filename"] == "valid_patch.zip"
    assert "ignored_zip_no_patch=1" in _status_text(payload)
