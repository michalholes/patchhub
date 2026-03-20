from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_zero_config_single_repo_target_selection_uses_runner_root_basename(tmp_path: Path) -> None:
    from am_patch.config import Policy
    from am_patch.root_model import resolve_root_model

    runner_root = tmp_path / "patchhub"
    runner_root.mkdir()

    model = resolve_root_model(Policy(), runner_root=runner_root)

    assert model.live_target_root == runner_root.resolve()
    assert model.active_repository_tree_root == runner_root.resolve()
    assert model.effective_target_repo_name == "patchhub"


def test_target_repo_config_relpath_escape_is_config_invalid(tmp_path: Path) -> None:
    from am_patch.config_file import resolve_repo_local_config_path
    from am_patch.errors import RunnerError

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(RunnerError) as excinfo:
        resolve_repo_local_config_path(
            active_repository_tree_root=repo_root,
            target_repo_config_relpath="../outside.toml",
        )

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"


@pytest.mark.parametrize("mode", ["workspace", "finalize_workspace"])
def test_active_repository_tree_root_uses_workspace_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    from am_patch.config import Policy
    from am_patch.startup_context import build_paths_and_logger

    live_root = tmp_path / "live"
    live_root.mkdir(parents=True)
    workspace_repo = tmp_path / "workspace" / "repo"
    (workspace_repo / ".am_patch").mkdir(parents=True)
    (workspace_repo / ".am_patch" / "am_patch.repo.toml").write_text(
        '[git]\ndefault_branch = "dev"\nrequire_up_to_date = false\n'
        "\n[promotion]\ncommit_and_push = false\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "am_patch.startup_context.git_ops.head_sha",
        lambda *args, **kwargs: "abc123",
    )
    if mode == "workspace":
        monkeypatch.setattr(
            "am_patch.startup_context.ensure_workspace",
            lambda *args, **kwargs: SimpleNamespace(repo=workspace_repo),
        )
        cli = SimpleNamespace(issue_id="101", mode="workspace", message="msg")
    else:
        monkeypatch.setattr(
            "am_patch.startup_context.open_existing_workspace",
            lambda *args, **kwargs: SimpleNamespace(repo=workspace_repo),
        )
        monkeypatch.setattr(
            "am_patch.startup_context.load_or_migrate_workspace_target_repo_name",
            lambda *args, **kwargs: "patchhub",
        )
        cli = SimpleNamespace(issue_id="101", mode="finalize_workspace", finalize_from_cwd=False)

    policy = Policy()
    policy.patch_dir = str(tmp_path / "patches")
    policy.target_repo_roots = [f"patchhub={live_root}"]
    policy.target_repo_name = "patchhub"
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.json_out = False
    policy.ipc_socket_enabled = False
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")

    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    try:
        assert ctx.live_target_root == live_root.resolve()
        assert ctx.active_repository_tree_root == workspace_repo.resolve()
        assert ctx.repo_root == live_root.resolve()
        assert ctx.policy.default_branch == "dev"
        assert ctx.policy.require_up_to_date is False
        assert ctx.policy.commit_and_push is False
    finally:
        ctx.status.stop()
        ctx.logger.close()
