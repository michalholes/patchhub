from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch import git_ops, runtime
from am_patch.cli_override_normalization import (
    apply_cli_symmetry_helpers,
    build_cli_override_mapping,
)
from am_patch.config import (
    REPO_OWNED_KEYS,
    apply_cli_overrides,
    build_policy,
    filter_policy_layer_cfg,
)
from am_patch.config_file import load_repo_local_config
from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
from am_patch.errors import RunnerError
from am_patch.gates import run_badguys
from am_patch.ipc_socket import IpcController
from am_patch.lock import FileLock
from am_patch.log import Logger, new_log_file
from am_patch.patch_input import PatchPlan, resolve_patch_plan
from am_patch.paths import default_paths, ensure_dirs
from am_patch.repo_root import resolve_repo_root_strict_from_cwd
from am_patch.root_model import resolve_patch_root, resolve_root_model
from am_patch.status import StatusReporter
from am_patch.workspace import (
    ensure_workspace,
    load_or_migrate_workspace_target_repo_name,
    open_existing_workspace,
)


@dataclass
class RunContext:
    cli: Any
    policy: Any
    config_path: Path
    used_cfg: str
    repo_root: Path
    patch_root: Path
    patch_dir: Path
    isolated_work_patch_dir: Path | None
    paths: Any
    log_path: Path
    json_path: Path | None
    logger: Logger
    status: StatusReporter
    verbosity: str
    log_level: str
    ipc: IpcController | None
    live_target_root: Path | None = None
    active_repository_tree_root: Path | None = None
    lock: FileLock | None = None
    runner_root: Path | None = None
    artifacts_root: Path | None = None
    effective_target_repo_name: str | None = None
    patch_plan: PatchPlan | None = None
    preopened_workspace: Any | None = None

    def __post_init__(self) -> None:
        if self.live_target_root is None:
            self.live_target_root = self.repo_root
        if self.active_repository_tree_root is None:
            self.active_repository_tree_root = self.repo_root


def _sync_repo_local_config_to_workspace_clone(
    *,
    live_target_root: Path,
    workspace_repo_root: Path,
    target_repo_config_relpath: str,
) -> None:
    relpath = str(target_repo_config_relpath or ".am_patch/am_patch.repo.toml").strip()
    if not relpath:
        return
    src = live_target_root / relpath
    if not src.is_file():
        return
    dst = workspace_repo_root / relpath
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def build_paths_and_logger(cli: Any, policy: Any, config_path: Path, used_cfg: str) -> RunContext:
    runner_root = Path(__file__).resolve().parents[2]
    _, patch_root = resolve_patch_root(policy, runner_root=runner_root)
    patch_plan: PatchPlan | None = None
    if cli.mode == "workspace" and cli.issue_id is not None:
        try:
            patch_plan = resolve_patch_plan(
                logger=None,
                cli=cli,
                policy=policy,
                issue_id=int(cli.issue_id),
                repo_root=runner_root,
                patch_root=patch_root,
            )
        except RunnerError as exc:
            if not (exc.stage == "PREFLIGHT" and exc.category == "MANIFEST"):
                raise

    workspace_target_repo_name: str | None = None
    if cli.mode == "finalize_workspace" and cli.issue_id is not None:
        workspace_target_repo_name = load_or_migrate_workspace_target_repo_name(
            patch_root / policy.patch_layout_workspaces_dir,
            str(cli.issue_id),
            issue_dir_template=policy.workspace_issue_dir_template,
            repo_dir_name=policy.workspace_repo_dir_name,
            meta_filename=policy.workspace_meta_filename,
            timeout_s=getattr(policy, "runner_subprocess_timeout_s", 0),
            write_back=False,
            runner_root=runner_root,
            target_repo_roots=list(getattr(policy, "target_repo_roots", []) or []),
        )

    if getattr(cli, "finalize_from_cwd", False):
        try:
            policy.active_target_repo_root = str(
                resolve_repo_root_strict_from_cwd(
                    timeout_s=getattr(policy, "runner_subprocess_timeout_s", 0)
                )
            )
        except RuntimeError as exc:
            raise RunnerError("CONFIG", "INVALID", str(exc)) from exc
        policy._src["active_target_repo_root"] = "cli"

    root_model = resolve_root_model(
        policy,
        runner_root=runner_root,
        patch_target_repo_name=(
            patch_plan.patch_target_repo_name if patch_plan is not None else None
        ),
        workspace_target_repo_name=workspace_target_repo_name,
    )
    live_target_root = root_model.live_target_root
    patch_root = root_model.patch_root
    effective_target_repo_name = root_model.effective_target_repo_name
    root_runner_root = root_model.runner_root
    root_artifacts_root = root_model.artifacts_root

    isolated_work_patch_dir: Path | None = None
    patch_dir = patch_root
    if (
        policy.test_mode
        and getattr(policy, "test_mode_isolate_patch_dir", True)
        and policy.patch_dir is None
        and cli.issue_id is not None
    ):
        isolated_work_patch_dir = (
            patch_root / "_test_mode" / f"issue_{cli.issue_id}_pid_{os.getpid()}"
        )
        patch_dir = isolated_work_patch_dir

    paths = default_paths(
        repo_root=live_target_root,
        patch_dir=patch_dir,
        logs_dir_name=policy.patch_layout_logs_dir,
        json_dir_name=policy.patch_layout_json_dir,
        workspaces_dir_name=policy.patch_layout_workspaces_dir,
        successful_dir_name=policy.patch_layout_successful_dir,
        unsuccessful_dir_name=policy.patch_layout_unsuccessful_dir,
        lockfile_name=policy.lockfile_name,
        current_log_symlink_name=policy.current_log_symlink_name,
    )
    ensure_dirs(paths)

    log_path = new_log_file(
        paths.logs_dir,
        issue_id=cli.issue_id,
        ts_format=policy.log_ts_format,
        issue_template=policy.log_template_issue,
        finalize_template=policy.log_template_finalize,
    )
    verbosity = getattr(policy, "verbosity", "verbose")
    log_level = getattr(policy, "log_level", "verbose")
    status = StatusReporter(enabled=(verbosity != "quiet"))
    json_path: Path | None = None
    if getattr(policy, "json_out", False):
        if cli.issue_id is not None:
            json_name = f"am_patch_issue_{cli.issue_id}.jsonl"
        else:
            json_name = "am_patch_finalize.jsonl"
        json_path = paths.json_dir / json_name

    startup = build_startup_logger_and_ipc(
        cli=cli,
        policy=policy,
        patch_dir=patch_dir,
        log_path=log_path,
        json_path=json_path,
        status=status,
        verbosity=verbosity,
        log_level=log_level,
        symlink_path=paths.symlink_path,
        effective_target_repo_name=effective_target_repo_name,
    )
    logger = startup.logger
    ipc = startup.ipc

    preopened_workspace: Any | None = None
    active_repository_tree_root = live_target_root
    if cli.mode == "workspace" and cli.issue_id is not None:
        try:
            live_base_sha = git_ops.head_sha(logger, live_target_root)
            preopened_workspace = ensure_workspace(
                logger=logger,
                workspaces_dir=paths.workspaces_dir,
                issue_id=cli.issue_id,
                live_repo=live_target_root,
                base_sha=live_base_sha,
                update=policy.update_workspace,
                soft_reset=policy.soft_reset_workspace,
                message=getattr(cli, "message", None),
                effective_target_repo_name=effective_target_repo_name,
                runner_root=runner_root,
                target_repo_roots=list(getattr(policy, "target_repo_roots", []) or []),
                timeout_s=getattr(policy, "runner_subprocess_timeout_s", 0),
                issue_dir_template=policy.workspace_issue_dir_template,
                repo_dir_name=policy.workspace_repo_dir_name,
                meta_filename=policy.workspace_meta_filename,
                history_logs_dir=policy.workspace_history_logs_dir,
                history_oldlogs_dir=policy.workspace_history_oldlogs_dir,
                history_patches_dir=policy.workspace_history_patches_dir,
                history_oldpatches_dir=policy.workspace_history_oldpatches_dir,
            )
        except (FileNotFoundError, NotADirectoryError):
            preopened_workspace = None
        else:
            active_repository_tree_root = preopened_workspace.repo
            _sync_repo_local_config_to_workspace_clone(
                live_target_root=live_target_root,
                workspace_repo_root=active_repository_tree_root,
                target_repo_config_relpath=policy.target_repo_config_relpath,
            )
    elif cli.mode == "finalize_workspace" and cli.issue_id is not None:
        preopened_workspace = open_existing_workspace(
            logger,
            paths.workspaces_dir,
            str(cli.issue_id),
            issue_dir_template=policy.workspace_issue_dir_template,
            repo_dir_name=policy.workspace_repo_dir_name,
            meta_filename=policy.workspace_meta_filename,
            timeout_s=getattr(policy, "runner_subprocess_timeout_s", 0),
            runner_root=runner_root,
            target_repo_roots=list(getattr(policy, "target_repo_roots", []) or []),
        )
        active_repository_tree_root = preopened_workspace.repo

    repo_cfg, _, _ = load_repo_local_config(
        active_repository_tree_root=active_repository_tree_root,
        target_repo_config_relpath=policy.target_repo_config_relpath,
    )
    repo_cfg = filter_policy_layer_cfg(repo_cfg, REPO_OWNED_KEYS)
    if repo_cfg:
        policy = build_policy(policy, repo_cfg, source_name="repo_config")
        apply_cli_overrides(policy, build_cli_override_mapping(cli))
        apply_cli_symmetry_helpers(policy, cli)

    status.start()

    runtime.status = status
    runtime.logger = logger
    runtime.policy = policy
    runtime.repo_root = live_target_root
    runtime.paths = paths
    runtime.cli = cli
    runtime.run_badguys = run_badguys
    runtime.RunnerError = RunnerError

    return RunContext(
        cli=cli,
        policy=policy,
        config_path=config_path,
        used_cfg=str(used_cfg),
        repo_root=live_target_root,
        live_target_root=live_target_root,
        active_repository_tree_root=active_repository_tree_root,
        patch_root=patch_root,
        patch_dir=patch_dir,
        isolated_work_patch_dir=isolated_work_patch_dir,
        paths=paths,
        log_path=log_path,
        json_path=json_path,
        logger=logger,
        status=status,
        verbosity=verbosity,
        log_level=log_level,
        ipc=ipc,
        runner_root=root_runner_root,
        artifacts_root=root_artifacts_root,
        effective_target_repo_name=effective_target_repo_name,
        patch_plan=patch_plan,
        preopened_workspace=preopened_workspace,
    )
