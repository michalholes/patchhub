from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _import_am_patch():
    from am_patch.config import Policy
    from am_patch.runtime import _is_runner_path
    from am_patch.startup_context import build_paths_and_logger

    return Policy, _is_runner_path, build_paths_and_logger


def test_runtime_runner_paths_match_amp_layout() -> None:
    _, is_runner_path, _ = _import_am_patch()

    assert is_runner_path("amp/am_patch.py") is True
    assert is_runner_path("amp/am_patch/runtime.py") is True
    assert is_runner_path("amp/am_patch.md") is True
    assert is_runner_path("scripts/am_patch.py") is False


def test_build_paths_and_logger_uses_active_target_repo_root(tmp_path: Path) -> None:
    policy_cls, _, build_paths_and_logger = _import_am_patch()

    target_a = tmp_path / "target_a"
    target_b = tmp_path / "target_b"
    artifacts = tmp_path / "artifacts"
    target_a.mkdir()
    target_b.mkdir()
    artifacts.mkdir()

    policy = policy_cls()
    policy.target_repo_roots = [str(target_a), str(target_b)]
    policy.active_target_repo_root = str(target_b)
    policy.artifacts_root = str(artifacts)
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.ipc_socket_enabled = False

    cli = SimpleNamespace(issue_id="1001", mode="workspace")
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")

    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    try:
        assert ctx.repo_root == target_b.resolve()
        assert ctx.artifacts_root == artifacts.resolve()
        assert ctx.patch_root == artifacts.resolve() / policy.patch_dir_name
        assert ctx.paths.patch_dir == ctx.patch_root
    finally:
        ctx.status.stop()
        ctx.logger.close()
