from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy
    from am_patch.engine import build_paths_and_logger
    from am_patch.errors import RunnerError
    from am_patch.log import Logger
    from am_patch.workspace import ensure_workspace, open_existing_workspace

    return (
        Policy,
        RunnerError,
        Logger,
        build_paths_and_logger,
        ensure_workspace,
        open_existing_workspace,
    )


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        capture_output=True,
        check=True,
    )


class _FakeLogger:
    def __init__(self, tmp_path: Path) -> None:
        _, _, logger_cls, _, _, _ = _import_am_patch()
        self._logger = logger_cls(
            log_path=tmp_path / "am_patch.log",
            symlink_path=tmp_path / "am_patch.symlink",
            screen_level="quiet",
            log_level="quiet",
            symlink_enabled=False,
            run_timeout_s=30,
        )

    def close(self) -> None:
        self._logger.close()

    def __getattr__(self, name: str):
        return getattr(self._logger, name)


def _init_repo(path: Path) -> None:
    if path.exists():
        subprocess.run(["rm", "-rf", str(path)], check=True)
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.name", "Tester")
    _git(path, "config", "user.email", "tester@example.com")
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "base.txt")
    _git(path, "commit", "-m", "base")


def _clone_repo(origin: Path, clone_path: Path) -> None:
    subprocess.run(
        ["git", "clone", str(origin), str(clone_path)],
        text=True,
        capture_output=True,
        check=True,
    )
    _git(clone_path, "config", "user.name", "Tester")
    _git(clone_path, "config", "user.email", "tester@example.com")


def _make_policy(tmp_path: Path):
    policy_cls, _, _, _, _, _ = _import_am_patch()
    policy = policy_cls()
    policy.patch_dir = str(tmp_path / "patches")
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.json_out = False
    policy.ipc_socket_enabled = False
    return policy


def _workspace_meta(meta_path: Path) -> dict[str, object]:
    return json.loads(meta_path.read_text(encoding="utf-8"))


def test_create_workspace_persists_target_repo_name(tmp_path: Path) -> None:
    (_, _, _, _, ensure_workspace, _) = _import_am_patch()
    origin = Path("/home/pi/issue999_create_target")
    live_repo = tmp_path / "live_repo"
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(origin)
    _clone_repo(origin, live_repo)
    base_sha = _git(live_repo, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        ws = ensure_workspace(
            logger,
            workspaces_dir,
            "999",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
    finally:
        logger.close()
    meta = _workspace_meta(ws.meta_path)
    assert meta["target_repo_name"] == "issue999_create_target"
    assert ws.target_repo_name == "issue999_create_target"


def test_open_existing_workspace_reads_target_repo_name(tmp_path: Path) -> None:
    (_, _, _, _, _, open_existing_workspace) = _import_am_patch()
    ws_root = tmp_path / "workspaces" / "issue_999"
    repo_dir = ws_root / "repo"
    repo_dir.mkdir(parents=True)
    meta_path = ws_root / "meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "base_sha": "abc123",
                "attempt": 4,
                "message": "hello",
                "target_repo_name": "patchhub",
            }
        ),
        encoding="utf-8",
    )
    logger = _FakeLogger(tmp_path)
    try:
        ws = open_existing_workspace(logger, tmp_path / "workspaces", "999")
    finally:
        logger.close()
    assert ws.target_repo_name == "patchhub"
    assert ws.attempt == 4
    assert ws.message == "hello"


def test_reuse_workspace_accepts_matching_target_from_live_origin(tmp_path: Path) -> None:
    (_, _, _, _, ensure_workspace, _) = _import_am_patch()
    origin = Path("/home/pi/issue999_reuse_same")
    live_repo = tmp_path / "live_repo"
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(origin)
    _clone_repo(origin, live_repo)
    base_sha = _git(live_repo, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        ensure_workspace(
            logger,
            workspaces_dir,
            "999",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
        ws = ensure_workspace(
            logger,
            workspaces_dir,
            "999",
            live_repo,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
    finally:
        logger.close()
    assert ws.target_repo_name == "issue999_reuse_same"


def test_reuse_workspace_rejects_mismatched_target(tmp_path: Path) -> None:
    (_, runner_error_cls, _, _, ensure_workspace, _) = _import_am_patch()
    origin_one = Path("/home/pi/issue999_reuse_one")
    origin_two = Path("/home/pi/issue999_reuse_two")
    live_one = tmp_path / "live_one"
    live_two = tmp_path / "live_two"
    workspaces_dir = tmp_path / "workspaces"
    _init_repo(origin_one)
    _init_repo(origin_two)
    _clone_repo(origin_one, live_one)
    _clone_repo(origin_two, live_two)
    base_sha = _git(live_one, "rev-parse", "HEAD").stdout.strip()
    logger = _FakeLogger(tmp_path)
    try:
        ensure_workspace(
            logger,
            workspaces_dir,
            "999",
            live_one,
            base_sha,
            update=False,
            soft_reset=False,
            message="msg",
        )
        with pytest.raises(runner_error_cls) as excinfo:
            ensure_workspace(
                logger,
                workspaces_dir,
                "999",
                live_two,
                base_sha,
                update=False,
                soft_reset=False,
                message="msg",
            )
    finally:
        logger.close()
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert "target_repo_name" in str(excinfo.value)


def test_finalize_workspace_uses_workspace_binding_before_lock_write_back(
    tmp_path: Path,
) -> None:
    policy_cls, _, _, build_paths_and_logger, _, open_existing_workspace = _import_am_patch()
    origin = Path("/home/pi/issue999_finalize_binding")
    live_repo = tmp_path / "live_repo"
    _init_repo(origin)
    _clone_repo(origin, live_repo)
    workspaces_dir = tmp_path / "patches" / "workspaces"
    ws_root = workspaces_dir / "issue_999"
    repo_dir = ws_root / "repo"
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    _clone_repo(origin, repo_dir)
    meta_path = ws_root / "meta.json"
    meta_path.write_text(
        json.dumps({"base_sha": "abc", "attempt": 1, "message": "msg"}),
        encoding="utf-8",
    )
    policy = policy_cls()
    policy.patch_dir = str(tmp_path / "patches")
    policy.target_repo_name = "rogue"
    policy.active_target_repo_root = "/home/pi/rogue"
    policy.repo_root = "/home/pi/rogue"
    policy.target_repo_roots = ["/home/pi/issue999_finalize_binding"]
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.json_out = False
    policy.ipc_socket_enabled = False
    cli = SimpleNamespace(issue_id="999", mode="finalize_workspace", finalize_from_cwd=False)
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")
    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    try:
        assert ctx.repo_root == Path("/home/pi/issue999_finalize_binding")
        assert "target_repo_name" not in _workspace_meta(meta_path)
        ws = open_existing_workspace(ctx.logger, workspaces_dir, "999")
    finally:
        if ctx.ipc is not None:
            ctx.ipc.stop()
        ctx.status.stop()
        ctx.logger.close()
    assert ws.target_repo_name == "issue999_finalize_binding"
    assert _workspace_meta(meta_path)["target_repo_name"] == "issue999_finalize_binding"


@pytest.mark.parametrize(
    ("origin_value", "should_pass"),
    [
        ("file:///home/pi/issue999_file_origin", True),
        ("https://example.com/repo.git", False),
    ],
)
def test_legacy_migration_accepts_only_canonical_local_or_file_origin(
    tmp_path: Path,
    origin_value: str,
    should_pass: bool,
) -> None:
    (_, runner_error_cls, _, _, _, open_existing_workspace) = _import_am_patch()
    origin = Path("/home/pi/issue999_file_origin")
    _init_repo(origin)
    workspaces_dir = tmp_path / "workspaces"
    repo_dir = workspaces_dir / "issue_999" / "repo"
    _clone_repo(origin, repo_dir)
    _git(repo_dir, "remote", "set-url", "origin", origin_value)
    meta_path = workspaces_dir / "issue_999" / "meta.json"
    meta_path.write_text(
        json.dumps({"base_sha": "abc", "attempt": 1, "message": "msg"}),
        encoding="utf-8",
    )
    logger = _FakeLogger(tmp_path)
    try:
        if should_pass:
            ws = open_existing_workspace(logger, workspaces_dir, "999")
            assert ws.target_repo_name == "issue999_file_origin"
        else:
            with pytest.raises(runner_error_cls) as excinfo:
                open_existing_workspace(logger, workspaces_dir, "999")
            assert excinfo.value.stage == "PREFLIGHT"
            assert excinfo.value.category == "WORKSPACE"
            assert "traceback" not in str(excinfo.value).lower()
    finally:
        logger.close()


def test_invalid_workspace_meta_json_fails_cleanly_without_rewrite(tmp_path: Path) -> None:
    (_, runner_error_cls, _, build_paths_and_logger, _, _) = _import_am_patch()
    origin = Path("/home/pi/issue999_invalid_meta")
    _init_repo(origin)
    repo_dir = tmp_path / "patches" / "workspaces" / "issue_999" / "repo"
    _clone_repo(origin, repo_dir)
    meta_path = repo_dir.parent / "meta.json"
    meta_path.write_text("{not-json", encoding="utf-8")
    policy = _make_policy(tmp_path)
    policy.target_repo_roots = ["/home/pi/issue999_invalid_meta"]
    cli = SimpleNamespace(issue_id="999", mode="finalize_workspace", finalize_from_cwd=False)
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")
    with pytest.raises(runner_error_cls) as excinfo:
        build_paths_and_logger(cli, policy, cfg, "test")
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert "meta.json is invalid" in excinfo.value.message
    assert meta_path.read_text(encoding="utf-8") == "{not-json"


def test_invalid_persisted_target_repo_name_fails_cleanly(tmp_path: Path) -> None:
    (_, runner_error_cls, _, _, _, open_existing_workspace) = _import_am_patch()
    origin = Path("/home/pi/issue999_invalid_target")
    _init_repo(origin)
    repo_dir = tmp_path / "workspaces" / "issue_999" / "repo"
    _clone_repo(origin, repo_dir)
    meta_path = repo_dir.parent / "meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "base_sha": "abc",
                "attempt": 1,
                "message": "msg",
                "target_repo_name": "bad/name",
            }
        ),
        encoding="utf-8",
    )
    logger = _FakeLogger(tmp_path)
    try:
        with pytest.raises(runner_error_cls) as excinfo:
            open_existing_workspace(logger, tmp_path / "workspaces", "999")
    finally:
        logger.close()
    assert excinfo.value.stage == "PREFLIGHT"
    assert excinfo.value.category == "WORKSPACE"
    assert str(excinfo.value).startswith("PREFLIGHT:WORKSPACE:")
