from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from am_patch.fs_junk import fs_junk_ignore_partition
from am_patch.workspace_history import (
    workspace_history_dirs,
    workspace_store_current_patch,
)


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    patch_dir: Path
    logs_dir: Path
    json_dir: Path
    workspaces_dir: Path
    successful_dir: Path
    unsuccessful_dir: Path
    artifacts_dir: Path
    lock_path: Path
    symlink_path: Path


def ensure_dirs(paths: Paths) -> None:
    for d in [
        paths.patch_dir,
        paths.logs_dir,
        paths.json_dir,
        paths.workspaces_dir,
        paths.successful_dir,
        paths.unsuccessful_dir,
        paths.artifacts_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def default_paths(
    repo_root: Path,
    patch_dir: Path,
    *,
    logs_dir_name: str = "logs",
    json_dir_name: str = "logs_json",
    workspaces_dir_name: str = "workspaces",
    successful_dir_name: str = "successful",
    unsuccessful_dir_name: str = "unsuccessful",
    lockfile_name: str = "am_patch.lock",
    current_log_symlink_name: str = "am_patch.log",
) -> Paths:
    logs_dir = patch_dir / logs_dir_name
    json_dir = patch_dir / json_dir_name
    workspaces_dir = patch_dir / workspaces_dir_name
    successful_dir = patch_dir / successful_dir_name
    unsuccessful_dir = patch_dir / unsuccessful_dir_name
    artifacts_dir = patch_dir / "artifacts"
    lock_path = patch_dir / lockfile_name
    symlink_path = patch_dir / current_log_symlink_name
    return Paths(
        repo_root=repo_root,
        patch_dir=patch_dir,
        logs_dir=logs_dir,
        json_dir=json_dir,
        workspaces_dir=workspaces_dir,
        successful_dir=successful_dir,
        unsuccessful_dir=unsuccessful_dir,
        artifacts_dir=artifacts_dir,
        lock_path=lock_path,
        symlink_path=symlink_path,
    )


def _fs_junk_ignore_partition(
    paths: list[str],
    *,
    ignore_prefixes: tuple[str, ...] | list[str],
    ignore_suffixes: tuple[str, ...] | list[str],
    ignore_contains: tuple[str, ...] | list[str],
) -> tuple[list[str], list[str]]:
    return fs_junk_ignore_partition(
        paths,
        ignore_prefixes=ignore_prefixes,
        ignore_suffixes=ignore_suffixes,
        ignore_contains=ignore_contains,
    )


def _workspace_history_dirs(
    ws_root: Path,
    *,
    history_logs_dir: str = "logs",
    history_oldlogs_dir: str = "oldlogs",
    history_patches_dir: str = "patches",
    history_oldpatches_dir: str = "oldpatches",
) -> tuple[Path, Path, Path, Path]:
    return workspace_history_dirs(
        ws_root,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )


def _workspace_store_current_patch(
    ws,
    patch_script: Path,
    *,
    history_logs_dir: str,
    history_oldlogs_dir: str,
    history_patches_dir: str,
    history_oldpatches_dir: str,
) -> None:
    return workspace_store_current_patch(
        ws,
        patch_script,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )
