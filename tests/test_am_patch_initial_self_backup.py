from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def section(self, title: str) -> None:
        self.events.append(("section", title))

    def line(self, s: str = "") -> None:
        self.events.append(("line", s))

    def info_core(self, s: str) -> None:
        self.events.append(("info", s))

    def run_logged(self, argv, cwd=None, **kwargs):
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
        return SimpleNamespace(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _touch(root: Path, rel: str, content: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _track_all(root: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)


def _policy(**overrides: object) -> SimpleNamespace:
    policy = {
        "self_backup_mode": "initial_self_patch",
        "self_backup_dir": "quarantine",
        "self_backup_template": "amp_self_backup_issue{issue}_{ts}.zip",
        "self_backup_include_relpaths": ["scripts/am_patch.py"],
        "log_ts_format": "%Y%m%d_%H%M%S",
    }
    policy.update(overrides)
    return SimpleNamespace(**policy)


def test_initial_self_backup_creates_zip_for_self_target_missing_workspace_repo() -> None:
    from am_patch.initial_self_backup import maybe_create_initial_self_backup

    with tempfile.TemporaryDirectory() as td:
        runner_root = Path(td) / "runner"
        artifacts_root = Path(td) / "artifacts"
        workspaces_dir = Path(td) / "patches" / "workspaces"
        runner_root.mkdir(parents=True)
        _init_git_repo(runner_root)
        _touch(runner_root, "scripts/am_patch.py", "print('root')\n")
        _touch(runner_root, "scripts/am_patch/__init__.py", "")
        _touch(runner_root, "scripts/am_patch/core.py", "print('core')\n")
        _track_all(runner_root)
        (runner_root / "scripts" / "am_patch" / "untracked.py").write_text(
            "print('skip')\n",
            encoding="utf-8",
        )

        logger = _FakeLogger()
        policy = _policy(
            self_backup_dir="quarantine/initial",
            self_backup_include_relpaths=["scripts/am_patch.py", "scripts/am_patch/"],
        )

        result = maybe_create_initial_self_backup(
            logger=logger,
            policy=policy,
            issue_id="364",
            runner_root=runner_root,
            live_target_root=runner_root,
            artifacts_root=artifacts_root,
            workspaces_dir=workspaces_dir,
            issue_dir_template="issue_{issue}",
            repo_dir_name="repo",
        )

        assert result.created is True
        assert result.skip_reason is None
        assert result.zip_path is not None
        assert result.zip_path.parent == artifacts_root / "quarantine" / "initial"
        with ZipFile(result.zip_path, "r") as zf:
            assert zf.namelist() == [
                "scripts/am_patch.py",
                "scripts/am_patch/__init__.py",
                "scripts/am_patch/core.py",
            ]


@pytest.mark.parametrize(
    ("live_root_name", "policy", "workspace_exists", "expected_reason"),
    [
        ("runner", _policy(), True, "workspace_exists"),
        ("live", _policy(), False, "not_self_target"),
        ("runner", _policy(self_backup_mode="never"), False, "mode_never"),
    ],
)
def test_initial_self_backup_skip_reasons(
    live_root_name: str,
    policy: SimpleNamespace,
    workspace_exists: bool,
    expected_reason: str,
) -> None:
    from am_patch.initial_self_backup import maybe_create_initial_self_backup

    with tempfile.TemporaryDirectory() as td:
        runner_root = Path(td) / "runner"
        live_target_root = Path(td) / live_root_name
        artifacts_root = Path(td) / "artifacts"
        workspaces_dir = Path(td) / "patches" / "workspaces"
        runner_root.mkdir(parents=True)
        live_target_root.mkdir(parents=True, exist_ok=True)
        _init_git_repo(runner_root)
        _touch(runner_root, "scripts/am_patch.py")
        _track_all(runner_root)
        if workspace_exists:
            (workspaces_dir / "issue_364" / "repo").mkdir(parents=True)

        result = maybe_create_initial_self_backup(
            logger=_FakeLogger(),
            policy=policy,
            issue_id="364",
            runner_root=runner_root,
            live_target_root=live_target_root,
            artifacts_root=artifacts_root,
            workspaces_dir=workspaces_dir,
            issue_dir_template="issue_{issue}",
            repo_dir_name="repo",
        )

        assert result.created is False
        assert result.skip_reason == expected_reason
        if expected_reason == "workspace_exists":
            assert not (artifacts_root / "quarantine").exists()


def test_initial_self_backup_accepts_override_include_relpaths() -> None:
    from am_patch.initial_self_backup import maybe_create_initial_self_backup

    with tempfile.TemporaryDirectory() as td:
        runner_root = Path(td) / "runner"
        artifacts_root = Path(td) / "artifacts"
        workspaces_dir = Path(td) / "patches" / "workspaces"
        runner_root.mkdir(parents=True)
        _init_git_repo(runner_root)
        _touch(runner_root, "extras/custom.py", "print('custom')\n")
        _track_all(runner_root)

        result = maybe_create_initial_self_backup(
            logger=_FakeLogger(),
            policy=_policy(self_backup_include_relpaths=["extras/custom.py"]),
            issue_id="364",
            runner_root=runner_root,
            live_target_root=runner_root,
            artifacts_root=artifacts_root,
            workspaces_dir=workspaces_dir,
            issue_dir_template="issue_{issue}",
            repo_dir_name="repo",
        )

        assert result.created is True
        assert result.archived_files == ("extras/custom.py",)


def test_startup_context_calls_self_backup_before_ensure_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    from am_patch.config import Policy
    from am_patch.startup_context import build_paths_and_logger

    order: list[str] = []
    workspace_repo = tmp_path / "workspace-repo"
    workspace_repo.mkdir(parents=True)

    class _Logger(_FakeLogger):
        def close(self) -> None:
            return

    fake_logger = _Logger()

    monkeypatch.setattr(
        "am_patch.startup_context.resolve_patch_plan",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "am_patch.startup_context.resolve_root_model",
        lambda *args, **kwargs: SimpleNamespace(
            live_target_root=tmp_path,
            patch_root=tmp_path / "patches",
            effective_target_repo_name="patchhub",
            runner_root=tmp_path,
            artifacts_root=tmp_path / "artifacts",
        ),
    )
    monkeypatch.setattr(
        "am_patch.startup_context.build_startup_logger_and_ipc",
        lambda *args, **kwargs: SimpleNamespace(logger=fake_logger, ipc=None),
    )
    monkeypatch.setattr(
        "am_patch.startup_context.git_ops.head_sha",
        lambda *args, **kwargs: "base-sha",
    )
    monkeypatch.setattr(
        "am_patch.startup_context.maybe_create_initial_self_backup",
        lambda *args, **kwargs: order.append("backup"),
    )
    monkeypatch.setattr(
        "am_patch.startup_context.ensure_workspace",
        lambda *args, **kwargs: order.append("ensure") or SimpleNamespace(repo=workspace_repo),
    )
    monkeypatch.setattr(
        "am_patch.startup_context.load_repo_local_config",
        lambda *args, **kwargs: ({}, None, None),
    )

    policy = Policy()
    policy.patch_dir = str(tmp_path / "patches")
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.json_out = False
    policy.ipc_socket_enabled = False
    cli = SimpleNamespace(issue_id="364", mode="workspace", finalize_from_cwd=False)
    cfg = tmp_path / "am_patch.toml"
    cfg.write_text("", encoding="utf-8")

    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    assert order == ["backup", "ensure"]
    ctx.status.stop()


def test_execution_context_calls_self_backup_before_ensure_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    from am_patch.execution_context import open_execution_context

    order: list[str] = []
    workspace = SimpleNamespace(
        root=tmp_path / "workspace",
        repo=tmp_path / "workspace" / "repo",
        base_sha="base-sha",
        attempt=1,
    )
    workspace.repo.mkdir(parents=True)

    monkeypatch.setattr("am_patch.execution_context.git_ops.fetch", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "am_patch.execution_context.git_ops.require_up_to_date",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "am_patch.execution_context.git_ops.require_branch",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "am_patch.execution_context.git_ops.head_sha",
        lambda *args, **kwargs: "base-sha",
    )
    monkeypatch.setattr(
        "am_patch.execution_context.resolve_patch_root",
        lambda *args, **kwargs: (tmp_path / "artifacts", tmp_path / "patches"),
    )
    monkeypatch.setattr(
        "am_patch.execution_context.maybe_create_initial_self_backup",
        lambda *args, **kwargs: order.append("backup"),
    )
    monkeypatch.setattr(
        "am_patch.execution_context.ensure_workspace",
        lambda *args, **kwargs: order.append("ensure") or workspace,
    )
    monkeypatch.setattr(
        "am_patch.execution_context.load_state",
        lambda *args, **kwargs: SimpleNamespace(allowed_union=set()),
    )
    monkeypatch.setattr(
        "am_patch.execution_context.create_checkpoint",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "am_patch.execution_context.changed_paths",
        lambda *args, **kwargs: [],
    )

    logger = _FakeLogger()
    policy = SimpleNamespace(
        require_up_to_date=False,
        skip_up_to_date=False,
        enforce_main_branch=False,
        allow_non_main=False,
        update_workspace=False,
        soft_reset_workspace=False,
        runner_subprocess_timeout_s=0,
        workspace_issue_dir_template="issue_{issue}",
        workspace_repo_dir_name="repo",
        workspace_meta_filename="meta.json",
        workspace_history_logs_dir="logs",
        workspace_history_oldlogs_dir="oldlogs",
        workspace_history_patches_dir="patches",
        workspace_history_oldpatches_dir="oldpatches",
        target_repo_roots=[],
        live_repo_guard=False,
        rollback_workspace_on_fail="never",
    )
    paths = SimpleNamespace(workspaces_dir=tmp_path / "patches" / "workspaces")
    cli = SimpleNamespace(issue_id="364", message="msg")

    open_execution_context(
        logger=logger,
        cli=cli,
        policy=policy,
        paths=paths,
        repo_root=tmp_path,
        runner_root=tmp_path,
        effective_target_repo_name="patchhub",
        patch_script=tmp_path / "issue_364_v1.zip",
        unified_mode=False,
        files_declared=[],
        preopened_workspace=None,
    )

    assert order == ["backup", "ensure"]
