from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import RunnerError

if TYPE_CHECKING:
    from .config import Policy


def validate_success_archive_retention(p: Policy) -> None:
    p.success_archive_dir = str(p.success_archive_dir).strip() or "patch_dir"
    if p.success_archive_dir not in ("patch_dir", "successful_dir"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "success_archive_dir must be patch_dir|successful_dir",
        )

    p.success_archive_cleanup_glob_template = str(p.success_archive_cleanup_glob_template).strip()

    if p.success_archive_keep_count < 0:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "success_archive_keep_count must be >= 0",
        )

    if p.success_archive_keep_count > 0 and not p.success_archive_cleanup_glob_template:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "success_archive_cleanup_glob_template must be non-empty when "
            "success_archive_keep_count > 0",
        )
