from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_am_patch_workspace_target_binding import (  # noqa: E402
    _clone_repo,
    _FakeLogger,
    _git,
    _import_am_patch,
    _init_repo,
    _workspace_meta,
)


def test_create_workspace_fails_before_side_effects_when_target_cannot_be_derived(
    tmp_path: Path,
) -> None:
    (_, runner_error_cls, _, _, ensure_workspace, _) = _import_am_patch()
    origin = tmp_path / "noncanonical_origin"
    live_repo = tmp_path / "live_repo"
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(origin)
    _clone_repo(origin, live_repo)
    base_sha = _git(live_repo, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        with pytest.raises(runner_error_cls) as excinfo:
            ensure_workspace(
                logger,
                workspaces_dir,
                "1000",
                live_repo,
                base_sha,
                update=False,
                soft_reset=False,
                message="msg",
            )
    finally:
        logger.close()
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert not (workspaces_dir / "issue_1000").exists()


@pytest.mark.parametrize(
    ("meta_payload", "expected_message"),
    [
        ({"base_sha": "abc", "attempt": 1}, "missing required message"),
        (
            {
                "base_sha": None,
                "attempt": 1,
                "message": "msg",
                "target_repo_name": "issue1000_null_base",
            },
            "invalid base_sha",
        ),
    ],
)
def test_open_existing_workspace_rejects_invalid_required_metadata(
    tmp_path: Path,
    meta_payload: dict[str, object],
    expected_message: str,
) -> None:
    (_, runner_error_cls, _, _, _, open_existing_workspace) = _import_am_patch()
    origin = Path("/home/pi/issue1000_null_base")
    _init_repo(origin)
    repo_dir = tmp_path / "workspaces" / "issue_1000" / "repo"
    _clone_repo(origin, repo_dir)
    meta_path = repo_dir.parent / "meta.json"
    meta_path.write_text(json.dumps(meta_payload), encoding="utf-8")
    logger = _FakeLogger(tmp_path)
    try:
        with pytest.raises(runner_error_cls) as excinfo:
            open_existing_workspace(logger, tmp_path / "workspaces", "1000")
    finally:
        logger.close()
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert expected_message in excinfo.value.message
    assert _workspace_meta(meta_path) == meta_payload


def test_reuse_workspace_keeps_recovered_target_repo_name(tmp_path: Path) -> None:
    (_, _, _, _, ensure_workspace, _) = _import_am_patch()
    live_repo = Path("/home/pi/issue1000_reuse_recover")
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(live_repo)
    base_sha = _git(live_repo, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        ws = ensure_workspace(
            logger,
            workspaces_dir,
            "1000",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
        meta = _workspace_meta(ws.meta_path)
        del meta["target_repo_name"]
        ws.meta_path.write_text(json.dumps(meta), encoding="utf-8")
        reused = ensure_workspace(
            logger,
            workspaces_dir,
            "1000",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
    finally:
        logger.close()
    assert reused.target_repo_name == "issue1000_reuse_recover"
    assert _workspace_meta(reused.meta_path)["target_repo_name"] == "issue1000_reuse_recover"


def test_reuse_workspace_rejects_null_target_repo_name_without_migration(
    tmp_path: Path,
) -> None:
    (_, runner_error_cls, _, _, ensure_workspace, _) = _import_am_patch()
    live_repo = Path("/home/pi/issue1000_null_target")
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(live_repo)
    base_sha = _git(live_repo, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        ws = ensure_workspace(
            logger,
            workspaces_dir,
            "1000",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
        meta = _workspace_meta(ws.meta_path)
        meta["target_repo_name"] = None
        ws.meta_path.write_text(json.dumps(meta), encoding="utf-8")
        with pytest.raises(runner_error_cls) as excinfo:
            ensure_workspace(
                logger,
                workspaces_dir,
                "1000",
                live_repo,
                base_sha,
                update=False,
                soft_reset=False,
                message="msg",
            )
    finally:
        logger.close()
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert "invalid target_repo_name" in excinfo.value.message
    assert _workspace_meta(ws.meta_path)["target_repo_name"] is None
