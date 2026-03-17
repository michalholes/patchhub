from __future__ import annotations

import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.archive import make_failure_zip
    from am_patch.failure_zip import cleanup_for_issue, render_name
    from am_patch.workspace import bump_existing_workspace_attempt

    return (
        bump_existing_workspace_attempt,
        cleanup_for_issue,
        render_name,
        make_failure_zip,
    )


@dataclass
class _PolicyStub:
    failure_zip_keep_per_issue: int = 1
    failure_zip_cleanup_glob_template: str = ""
    failure_zip_template: str = "patched_issue{issue}_v{attempt:02d}.zip"
    log_template_issue: str = "i_{issue}_{ts}.log"
    log_template_finalize: str = "f_{ts}.log"
    failure_zip_name: str = "patched.zip"


def test_finalize_attempt_bump_updates_meta(tmp_path: Path) -> None:
    bump_attempt, _, _, _ = _import_am_patch()

    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({"attempt": 3}), encoding="utf-8")

    new_attempt = bump_attempt(meta_path)
    assert new_attempt == 4
    obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert int(obj.get("attempt")) == 4


def test_retention_after_write_keep_one(tmp_path: Path) -> None:
    _, cleanup_for_issue, _, _ = _import_am_patch()
    policy = _PolicyStub(failure_zip_keep_per_issue=1)
    patch_dir = tmp_path

    (patch_dir / "patched_issue254_v03.zip").write_bytes(b"x")
    (patch_dir / "patched_issue254_v04.zip").write_bytes(b"x")

    cleanup_for_issue(patch_dir=patch_dir, policy=policy, issue="254")

    assert not (patch_dir / "patched_issue254_v03.zip").exists()
    assert (patch_dir / "patched_issue254_v04.zip").exists()


def test_render_uses_propagated_attempt(tmp_path: Path) -> None:
    _, _, render_name, _ = _import_am_patch()
    policy = _PolicyStub(failure_zip_template="patched_issue{issue}_v{attempt:02d}.zip")

    log_path = tmp_path / "i_254_20200101.log"
    log_path.write_text("x", encoding="utf-8")

    name = render_name(policy=policy, issue="254", log_path=log_path, attempt=4)
    assert name.endswith("_v04.zip")


@dataclass
class _LoggerStub:
    def section(self, _name: str) -> None:
        return None

    def line(self, _message: str) -> None:
        return None

    def info_core(self, _message: str) -> None:
        return None


def test_make_failure_zip_writes_root_target_txt(tmp_path: Path) -> None:
    _, _, _, make_failure_zip = _import_am_patch()

    workspace_repo = tmp_path / "repo"
    workspace_repo.mkdir()
    (workspace_repo / "scripts").mkdir()
    (workspace_repo / "scripts" / "sample.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )

    log_path = tmp_path / "run.log"
    log_path.write_text("log\n", encoding="utf-8")
    zip_path = tmp_path / "patched.zip"

    make_failure_zip(
        _LoggerStub(),
        zip_path,
        workspace_repo=workspace_repo,
        log_path=log_path,
        include_repo_files=["scripts/sample.py"],
        target_repo_name="patchhub",
    )

    with zipfile.ZipFile(zip_path, "r") as zf:
        assert "target.txt" in zf.namelist()
        assert zf.read("target.txt") == b"patchhub\n"


def test_failure_zip_target_is_derived_from_selected_effective_root(
    tmp_path: Path,
) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.artifacts import build_artifacts

    @dataclass
    class _CliStub:
        mode: str = "workspace"
        issue_id: str | None = "993"

    @dataclass
    class _PathsStub:
        patch_dir: Path
        artifacts_dir: Path
        logs_dir: Path

    workspace_repo = tmp_path / "repo"
    workspace_repo.mkdir()
    (workspace_repo / "scripts").mkdir()
    (workspace_repo / "scripts" / "sample.py").write_text(
        "print('ok')\n", encoding="utf-8"
    )

    patch_dir = tmp_path / "patches"
    artifacts_dir = patch_dir / "artifacts"
    logs_dir = patch_dir / "logs"
    artifacts_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)

    log_path = logs_dir / "run.log"
    log_path.write_text("log\n", encoding="utf-8")

    policy = _PolicyStub()
    policy.failure_zip_log_dir = "logs"
    policy.failure_zip_patch_dir = "patches"

    build_artifacts(
        logger=_LoggerStub(),
        cli=_CliStub(),
        policy=policy,
        paths=_PathsStub(
            patch_dir=patch_dir, artifacts_dir=artifacts_dir, logs_dir=logs_dir
        ),
        repo_root=Path("/home/pi/patchhub"),
        log_path=log_path,
        exit_code=1,
        unified_mode=True,
        patch_applied_successfully=False,
        archived_patch=None,
        failed_patch_blobs_for_zip=[],
        files_for_fail_zip=["scripts/sample.py"],
        ws_repo_for_fail_zip=workspace_repo,
        ws_attempt=4,
        issue_diff_base_sha=None,
        issue_diff_paths=[],
    )

    zip_path = patch_dir / "patched_issue993_v04.zip"
    with zipfile.ZipFile(zip_path, "r") as zf:
        assert zf.read("target.txt") == b"patchhub\n"


def test_failure_zip_target_derivation_rejects_noncanonical_root() -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.errors import RunnerError
    from am_patch.root_model import canonical_target_repo_name_from_root

    try:
        canonical_target_repo_name_from_root(Path("/tmp/not-canonical"))
    except RunnerError as exc:
        assert exc.stage == "CONFIG"
        assert exc.category == "INVALID"
    else:
        raise AssertionError("expected RunnerError")


def _write_issue_zip(zip_path: Path, *, target: str | None) -> None:
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "patches/per_file/scripts__sample.py.patch",
            "diff --git a/scripts/sample.py b/scripts/sample.py\n",
        )
        if target is not None:
            zf.writestr("target.txt", f"{target}\n")


def _policy_from_shipped_config(tmp_path: Path, *, target_repo_name: str | None = None):
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.config import Policy, build_policy, load_config

    config_path = scripts_dir / "am_patch" / "am_patch.toml"
    cfg, _ = load_config(config_path)
    if target_repo_name is not None:
        cfg["target_repo_name"] = target_repo_name
    policy = build_policy(Policy(), cfg)
    policy.patch_dir = str(tmp_path / "patches")
    policy.current_log_symlink_enabled = False
    policy.verbosity = "quiet"
    policy.log_level = "quiet"
    policy.ipc_socket_enabled = False
    return config_path, policy


def test_patch_target_selection_scenarios(tmp_path: Path) -> None:
    from types import SimpleNamespace

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.config import Policy
    from am_patch.startup_context import build_paths_and_logger

    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    cfg = tmp_path / "am_patch_test.toml"
    cfg.write_text("", encoding="utf-8")

    registry = ["/home/pi/audiomason2", "/home/pi/patchhub"]

    def _ctx_for(target: str | None, *, active_root: str | None = None):
        zip_path = patch_dir / "issue_993.zip"
        if zip_path.exists():
            zip_path.unlink()
        _write_issue_zip(zip_path, target=target)
        policy = Policy()
        policy.patch_dir = str(patch_dir)
        policy.target_repo_roots = list(registry)
        policy.current_log_symlink_enabled = False
        policy.verbosity = "quiet"
        policy.log_level = "quiet"
        policy.ipc_socket_enabled = False
        if active_root is not None:
            policy.active_target_repo_root = active_root
            policy._src["active_target_repo_root"] = "cli"
        cli = SimpleNamespace(
            issue_id="993",
            mode="workspace",
            patch_script=None,
            load_latest_patch=None,
        )
        return build_paths_and_logger(cli, policy, cfg, "test")

    ctx = _ctx_for(None)
    try:
        assert ctx.repo_root == Path("/home/pi/audiomason2")
        assert ctx.effective_target_repo_name == "audiomason2"
    finally:
        ctx.status.stop()
        ctx.logger.close()

    ctx = _ctx_for("audiomason2")
    try:
        assert ctx.repo_root == Path("/home/pi/audiomason2")
        assert ctx.effective_target_repo_name == "audiomason2"
    finally:
        ctx.status.stop()
        ctx.logger.close()

    ctx = _ctx_for("audiomason2", active_root="/home/pi/patchhub")
    try:
        assert ctx.repo_root == Path("/home/pi/patchhub")
        assert ctx.effective_target_repo_name == "patchhub"
    finally:
        ctx.status.stop()
        ctx.logger.close()

    ctx = _ctx_for("patchhub")
    try:
        assert ctx.repo_root == Path("/home/pi/patchhub")
        assert ctx.effective_target_repo_name == "patchhub"
    finally:
        ctx.status.stop()
        ctx.logger.close()


def test_root_model_rejects_selected_noncanonical_root() -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.config import Policy
    from am_patch.errors import RunnerError
    from am_patch.root_model import resolve_root_model

    policy = Policy()
    policy.target_repo_roots = ["/tmp/not-canonical"]
    policy.active_target_repo_root = "/tmp/not-canonical"
    policy._src["active_target_repo_root"] = "config"

    try:
        resolve_root_model(policy, runner_root=Path("/home/pi/audiomason2"))
    except RunnerError as exc:
        assert exc.stage == "CONFIG"
        assert exc.category == "INVALID"
    else:
        raise AssertionError("expected RunnerError")


def test_nonworkspace_target_repo_name_uses_target_selection_contract(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.startup_context import build_paths_and_logger

    cfg, policy = _policy_from_shipped_config(tmp_path, target_repo_name="patchhub")
    cli = SimpleNamespace(
        issue_id=None,
        mode="finalize",
        patch_script=None,
        load_latest_patch=None,
    )

    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    try:
        assert ctx.repo_root == Path("/home/pi/patchhub")
        assert ctx.effective_target_repo_name == "patchhub"
    finally:
        ctx.status.stop()
        ctx.logger.close()


def test_workspace_invalid_patch_target_fails_before_root_binding(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.errors import RunnerError
    from am_patch.startup_context import build_paths_and_logger

    cfg, policy = _policy_from_shipped_config(tmp_path)
    patch_dir = Path(policy.patch_dir)
    patch_dir.mkdir(parents=True)
    _write_issue_zip(patch_dir / "issue_993.zip", target="bad/name")

    cli = SimpleNamespace(
        issue_id="993",
        mode="workspace",
        patch_script=None,
        load_latest_patch=None,
    )

    try:
        build_paths_and_logger(cli, policy, cfg, "test")
    except RunnerError as exc:
        assert exc.stage == "PREFLIGHT"
        assert exc.category == "PATCH_PATH"
    else:
        raise AssertionError("expected RunnerError")


def test_shipped_config_default_target_registry_supports_default_target_name(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.startup_context import build_paths_and_logger

    cfg, policy = _policy_from_shipped_config(tmp_path)
    cli = SimpleNamespace(
        issue_id=None,
        mode="finalize",
        patch_script=None,
        load_latest_patch=None,
    )

    ctx = build_paths_and_logger(cli, policy, cfg, "test")
    try:
        assert ctx.repo_root == Path("/home/pi/audiomason2")
        assert ctx.effective_target_repo_name == "audiomason2"
    finally:
        ctx.status.stop()
        ctx.logger.close()
