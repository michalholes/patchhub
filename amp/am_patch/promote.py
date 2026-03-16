from __future__ import annotations

import shutil
from pathlib import Path

from . import git_ops
from .errors import RunnerError
from .log import Logger


def promote_files(
    *,
    logger: Logger,
    workspace_repo: Path,
    live_repo: Path,
    base_sha: str,
    files_to_promote: list[str],
    fail_if_live_changed: bool,
    live_changed_resolution: str,
) -> None:
    logger.section("PROMOTION")
    logger.info_core(f"promotion=START base_sha={base_sha} files={len(files_to_promote)}")
    logger.line(f"base_sha={base_sha}")
    logger.line(f"files_to_promote={files_to_promote}")

    changed_live: list[str] = []
    if files_to_promote:
        changed_live = git_ops.files_changed_since(logger, live_repo, base_sha, files_to_promote)

    if changed_live:
        logger.warning_core(f"promotion_live_changed={changed_live}")
        if live_changed_resolution == "overwrite_workspace":
            logger.line(
                "live repo changed since base_sha for some files; dropping from promotion: "
                f"{changed_live}"
            )
            files_to_promote = [f for f in files_to_promote if f not in set(changed_live)]
        elif live_changed_resolution == "overwrite_live":
            logger.line(
                "live repo changed since base_sha for some files; overwriting live with workspace: "
                f"{changed_live}"
            )
        else:
            # fail
            if fail_if_live_changed:
                raise RunnerError(
                    "PROMOTION",
                    "LIVE_CHANGED",
                    (
                        f"live repo changed since base_sha for files: {changed_live} "
                        "(use -W/--update-workspace, --overwrite-live/--overwrite-workspace, "
                        "or set live_changed_resolution)"
                    ),
                )

    for rel in files_to_promote:
        src = workspace_repo / rel
        dst = live_repo / rel

        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.line(f"copied: {rel}")
        else:
            # File deleted in workspace => delete in live
            if dst.exists():
                dst.unlink()
                logger.line(f"deleted: {rel}")
            else:
                logger.line(f"missing in workspace and live: {rel} (noop)")

    # Stage promoted files
    if files_to_promote:
        r = logger.run_logged(
            ["git", "add", "--"] + files_to_promote,
            cwd=live_repo,
            timeout_stage="PROMOTION",
        )
        if r.returncode != 0:
            raise RunnerError("PROMOTION", "GIT", "git add failed")

    logger.info_core(
        f"promotion=OK promoted={len(files_to_promote)} live_changed={len(changed_live)}"
    )
