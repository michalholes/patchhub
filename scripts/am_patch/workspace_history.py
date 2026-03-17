from __future__ import annotations

import shutil
from pathlib import Path


def workspace_history_dirs(
    ws_root: Path,
    *,
    history_logs_dir: str = "logs",
    history_oldlogs_dir: str = "oldlogs",
    history_patches_dir: str = "patches",
    history_oldpatches_dir: str = "oldpatches",
) -> tuple[Path, Path, Path, Path]:
    logs_dir = ws_root / history_logs_dir
    oldlogs_dir = ws_root / history_oldlogs_dir
    patches_dir = ws_root / history_patches_dir
    oldpatches_dir = ws_root / history_oldpatches_dir
    for d in [logs_dir, oldlogs_dir, patches_dir, oldpatches_dir]:
        d.mkdir(parents=True, exist_ok=True)
    return logs_dir, oldlogs_dir, patches_dir, oldpatches_dir


def rotate_current_dir(cur_dir: Path, old_dir: Path, prev_attempt: int) -> None:
    if prev_attempt <= 0:
        return
    old_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(cur_dir.glob("*")):
        if not p.is_file():
            continue
        new_name = f"{p.stem}_[attempt{prev_attempt}]{p.suffix}"
        p.replace(old_dir / new_name)


def workspace_store_current_patch(
    ws,
    patch_script: Path,
    *,
    history_logs_dir: str,
    history_oldlogs_dir: str,
    history_patches_dir: str,
    history_oldpatches_dir: str,
) -> None:
    logs_dir, oldlogs_dir, patches_dir, oldpatches_dir = workspace_history_dirs(
        ws.root,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )
    _ = logs_dir
    _ = oldlogs_dir

    prev_attempt = int(ws.attempt) - 1
    rotate_current_dir(patches_dir, oldpatches_dir, prev_attempt)

    # Keep the current patch under its original filename (no suffix).
    dst = patches_dir / patch_script.name
    shutil.copy2(patch_script, dst)


def workspace_store_current_log(
    ws,
    log_path: Path,
    *,
    history_logs_dir: str,
    history_oldlogs_dir: str,
    history_patches_dir: str,
    history_oldpatches_dir: str,
) -> None:
    logs_dir, oldlogs_dir, patches_dir, oldpatches_dir = workspace_history_dirs(
        ws.root,
        history_logs_dir=history_logs_dir,
        history_oldlogs_dir=history_oldlogs_dir,
        history_patches_dir=history_patches_dir,
        history_oldpatches_dir=history_oldpatches_dir,
    )
    _ = patches_dir
    _ = oldpatches_dir

    prev_attempt = int(ws.attempt) - 1
    rotate_current_dir(logs_dir, oldlogs_dir, prev_attempt)

    # Keep the current log under its original filename (no suffix).
    dst = logs_dir / log_path.name
    shutil.copy2(log_path, dst)
