from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


def _import_am_patch():
    """Import am_patch.* from scripts/ for unit tests."""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod
    from am_patch.config import Policy as PolicyCls
    from am_patch.engine import build_paths_and_logger

    return PolicyCls, build_paths_and_logger, runtime_mod


def test_test_mode_isolates_patch_dir_layout(tmp_path: Path) -> None:
    policy_cls, build_paths_and_logger, runtime_mod = _import_am_patch()

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "run_badguys": runtime_mod.run_badguys,
        "RunnerError": runtime_mod.RunnerError,
    }

    ctx = None
    try:
        policy = policy_cls()
        policy.target_repo_roots = ["/home/pi/audiomason2"]
        policy.test_mode = True
        policy.test_mode_isolate_patch_dir = True
        policy.patch_dir = None
        policy.verbosity = "quiet"
        policy.log_level = "quiet"
        policy.current_log_symlink_enabled = False

        cli = SimpleNamespace(issue_id="999", mode="workspace")
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = build_paths_and_logger(cli, policy, cfg, "test")
        expected = ctx.patch_root / "_test_mode" / f"issue_{cli.issue_id}_pid_{os.getpid()}"
        assert ctx.patch_root == ctx.runner_root / policy.patch_dir_name
        assert ctx.patch_dir == expected

        assert ctx.paths.patch_dir == ctx.patch_dir
        assert ctx.paths.logs_dir == ctx.patch_dir / policy.patch_layout_logs_dir
        assert ctx.paths.json_dir == ctx.patch_dir / policy.patch_layout_json_dir
        assert ctx.paths.workspaces_dir == ctx.patch_dir / policy.patch_layout_workspaces_dir
        assert ctx.paths.artifacts_dir == ctx.patch_dir / "artifacts"
        assert ctx.paths.lock_path.parent == ctx.patch_dir
        assert ctx.paths.symlink_path.parent == ctx.patch_dir

        assert ctx.ipc is not None
        assert ctx.ipc.socket_path.parent == ctx.patch_dir
    finally:
        if ctx is not None:
            if ctx.ipc is not None:
                ctx.ipc.stop()
            ctx.status.stop()
            ctx.logger.close()
        for k, v in old.items():
            setattr(runtime_mod, k, v)
