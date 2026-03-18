from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch import runtime
from am_patch.engine_startup_runtime import build_startup_logger_and_ipc
from am_patch.errors import RunnerError
from am_patch.gates import run_badguys
from am_patch.ipc_socket import IpcController
from am_patch.lock import FileLock
from am_patch.log import Logger, new_log_file
from am_patch.patch_input import PatchPlan, resolve_patch_plan
from am_patch.paths import default_paths, ensure_dirs
from am_patch.root_model import resolve_patch_root, resolve_root_model
from am_patch.status import StatusReporter


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
    lock: FileLock | None = None
    runner_root: Path | None = None
    artifacts_root: Path | None = None
    effective_target_repo_name: str | None = None
    patch_plan: PatchPlan | None = None


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

    root_model = resolve_root_model(
        policy,
        runner_root=runner_root,
        patch_target_repo_name=(
            patch_plan.patch_target_repo_name if patch_plan is not None else None
        ),
    )
    repo_root = root_model.active_target_repo_root
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
        repo_root=repo_root,
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
    )
    logger = startup.logger
    ipc = startup.ipc

    status.start()

    runtime.status = status
    runtime.logger = logger
    runtime.policy = policy
    runtime.repo_root = repo_root
    runtime.paths = paths
    runtime.cli = cli
    runtime.run_badguys = run_badguys
    runtime.RunnerError = RunnerError

    return RunContext(
        cli=cli,
        policy=policy,
        config_path=config_path,
        used_cfg=str(used_cfg),
        repo_root=repo_root,
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
    )
