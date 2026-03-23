from __future__ import annotations

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

    return Policy, RunnerError, build_paths_and_logger


def _runtime_state():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod

    old = {
        "status": runtime_mod.status,
        "logger": runtime_mod.logger,
        "policy": runtime_mod.policy,
        "repo_root": runtime_mod.repo_root,
        "paths": runtime_mod.paths,
        "cli": runtime_mod.cli,
        "RunnerError": runtime_mod.RunnerError,
    }
    return runtime_mod, old


def _make_policy(tmp_path: Path):
    policy_cls, _, _ = _import_am_patch()
    policy = policy_cls()
    policy.patch_dir = str(tmp_path / "patches")
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.json_out = False
    policy.ipc_socket_enabled = False
    return policy


def _make_cli() -> SimpleNamespace:
    return SimpleNamespace(issue_id=None, mode="finalize", finalize_from_cwd=True)


def test_finalize_from_cwd_materializes_active_target_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, build_paths_and_logger = _import_am_patch()
    runtime_mod, old = _runtime_state()
    resolved = (tmp_path / "targets" / "patchhub").resolve()
    monkeypatch.setattr(
        "am_patch.startup_context.resolve_repo_root_strict_from_cwd",
        lambda timeout_s=0: resolved,
    )

    ctx = None
    try:
        policy = _make_policy(tmp_path)
        policy.target_repo_roots = [f"patchhub={resolved}"]
        cfg = tmp_path / "am_patch_test.toml"
        cfg.write_text("", encoding="utf-8")

        ctx = build_paths_and_logger(_make_cli(), policy, cfg, "test")

        assert policy.active_target_repo_root == str(resolved)
        assert policy._src["active_target_repo_root"] == "cli"
        assert ctx.repo_root == resolved
    finally:
        if ctx is not None:
            ctx.status.stop()
            ctx.logger.close()
        for key, value in old.items():
            setattr(runtime_mod, key, value)


def test_finalize_from_cwd_strict_helper_error_is_config_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, runner_error_cls, build_paths_and_logger = _import_am_patch()
    monkeypatch.setattr(
        "am_patch.startup_context.resolve_repo_root_strict_from_cwd",
        lambda timeout_s=0: (_ for _ in ()).throw(RuntimeError("strict failure")),
    )
    policy = _make_policy(tmp_path)
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")

    with pytest.raises(runner_error_cls) as excinfo:
        build_paths_and_logger(_make_cli(), policy, cfg, "test")

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"
    assert "strict failure" in excinfo.value.message


def test_finalize_from_cwd_still_uses_existing_root_allowlist_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, runner_error_cls, build_paths_and_logger = _import_am_patch()
    monkeypatch.setattr(
        "am_patch.startup_context.resolve_repo_root_strict_from_cwd",
        lambda timeout_s=0: (tmp_path / "targets" / "rogue").resolve(),
    )
    policy = _make_policy(tmp_path)
    patchhub_root = (tmp_path / "targets" / "patchhub").resolve()
    policy.target_repo_roots = [f"patchhub={patchhub_root}"]
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")

    with pytest.raises(runner_error_cls) as excinfo:
        build_paths_and_logger(_make_cli(), policy, cfg, "test")

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"
    assert (
        "active_target_repo_root must resolve to an entry from target_repo_roots"
        in excinfo.value.message
    )


@pytest.mark.parametrize(
    "target_repo_roots",
    [
        [
            "patchhub=/srv/targets/patchhub",
            "patchhub=/srv/targets/patchhub_backup",
        ],
        [
            "patchhub=/srv/targets/patchhub",
            "mirror=/srv/targets/patchhub",
        ],
    ],
)
def test_duplicate_binding_registry_entries_fail_config_invalid(
    target_repo_roots: list[str], tmp_path: Path
) -> None:
    _, runner_error_cls, build_paths_and_logger = _import_am_patch()
    policy = _make_policy(tmp_path)
    policy.target_repo_roots = target_repo_roots
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")
    cli = SimpleNamespace(issue_id="999", mode="workspace")

    with pytest.raises(runner_error_cls) as excinfo:
        build_paths_and_logger(cli, policy, cfg, "test")

    assert excinfo.value.stage == "CONFIG"
    assert excinfo.value.category == "INVALID"
    assert "duplicate target_repo_roots" in excinfo.value.message


def test_runtime_module_has_no_special_badguys_hook() -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.runtime as runtime_mod

    assert not hasattr(runtime_mod, "_is_runner_path")
    assert not hasattr(runtime_mod, "_runner_touched")
    assert not hasattr(runtime_mod, "_maybe_run_badguys")
