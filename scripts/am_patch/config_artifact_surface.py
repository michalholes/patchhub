from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import RunnerError
from .success_archive_retention import validate_success_archive_retention

ConfigBool = Callable[[dict[str, Any], str, bool], bool]
MarkCfg = Callable[[Any, dict[str, Any], str], None]
ValidateBasename = Callable[[str, str], str]


def apply_artifact_cfg_surface(
    cfg: dict[str, Any],
    p: Any,
    *,
    as_bool: ConfigBool,
    mark_cfg: MarkCfg,
) -> None:
    p.failure_zip_enabled = as_bool(cfg, "failure_zip_enabled", p.failure_zip_enabled)
    mark_cfg(p, cfg, "failure_zip_enabled")
    p.patch_script_archive_enabled = as_bool(
        cfg,
        "patch_script_archive_enabled",
        p.patch_script_archive_enabled,
    )
    mark_cfg(p, cfg, "patch_script_archive_enabled")
    p.failure_zip_name = str(cfg.get("failure_zip_name", p.failure_zip_name))
    mark_cfg(p, cfg, "failure_zip_name")
    p.failure_zip_template = str(cfg.get("failure_zip_template", p.failure_zip_template))
    mark_cfg(p, cfg, "failure_zip_template")
    p.failure_zip_cleanup_glob_template = str(
        cfg.get("failure_zip_cleanup_glob_template", p.failure_zip_cleanup_glob_template)
    )
    mark_cfg(p, cfg, "failure_zip_cleanup_glob_template")
    if "failure_zip_keep_per_issue" in cfg:
        p.failure_zip_keep_per_issue = int(cfg["failure_zip_keep_per_issue"])
        mark_cfg(p, cfg, "failure_zip_keep_per_issue")
    p.failure_zip_delete_on_success_commit = as_bool(
        cfg,
        "failure_zip_delete_on_success_commit",
        p.failure_zip_delete_on_success_commit,
    )
    mark_cfg(p, cfg, "failure_zip_delete_on_success_commit")
    p.failure_zip_log_dir = str(cfg.get("failure_zip_log_dir", p.failure_zip_log_dir))
    mark_cfg(p, cfg, "failure_zip_log_dir")
    p.failure_zip_patch_dir = str(cfg.get("failure_zip_patch_dir", p.failure_zip_patch_dir))
    mark_cfg(p, cfg, "failure_zip_patch_dir")

    p.success_archive_enabled = as_bool(
        cfg,
        "success_archive_enabled",
        p.success_archive_enabled,
    )
    mark_cfg(p, cfg, "success_archive_enabled")
    p.artifact_stage_enabled = as_bool(
        cfg,
        "artifact_stage_enabled",
        p.artifact_stage_enabled,
    )
    mark_cfg(p, cfg, "artifact_stage_enabled")
    p.success_archive_name = str(cfg.get("success_archive_name", p.success_archive_name))
    mark_cfg(p, cfg, "success_archive_name")
    p.success_archive_dir = str(cfg.get("success_archive_dir", p.success_archive_dir))
    mark_cfg(p, cfg, "success_archive_dir")
    p.success_archive_cleanup_glob_template = str(
        cfg.get(
            "success_archive_cleanup_glob_template",
            p.success_archive_cleanup_glob_template,
        )
    )
    mark_cfg(p, cfg, "success_archive_cleanup_glob_template")
    if "success_archive_keep_count" in cfg:
        p.success_archive_keep_count = int(cfg["success_archive_keep_count"])
        mark_cfg(p, cfg, "success_archive_keep_count")

    p.issue_diff_bundle_enabled = as_bool(
        cfg,
        "issue_diff_bundle_enabled",
        p.issue_diff_bundle_enabled,
    )
    mark_cfg(p, cfg, "issue_diff_bundle_enabled")


def validate_artifact_cfg_surface(
    p: Any,
    *,
    validate_basename: ValidateBasename,
) -> None:
    p.failure_zip_name = validate_basename(p.failure_zip_name, "failure_zip_name")

    p.failure_zip_template = str(p.failure_zip_template).strip()
    if p.failure_zip_template and "{issue}" not in p.failure_zip_template:
        raise RunnerError("CONFIG", "INVALID", "failure_zip_template must contain {issue}")

    if p.failure_zip_template:
        uniqueness_keys = ("{ts}", "{nonce}", "{attempt")
        if not any(k in p.failure_zip_template for k in uniqueness_keys):
            raise RunnerError(
                "CONFIG",
                "INVALID",
                ("failure_zip_template must contain at least one of {ts}, {nonce}, {attempt}"),
            )

    p.failure_zip_cleanup_glob_template = validate_basename(
        p.failure_zip_cleanup_glob_template,
        "failure_zip_cleanup_glob_template",
    )
    if p.failure_zip_keep_per_issue < 0:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "failure_zip_keep_per_issue must be >= 0",
        )

    validate_success_archive_retention(p)
    p.failure_zip_log_dir = validate_basename(p.failure_zip_log_dir, "failure_zip_log_dir")
    p.failure_zip_patch_dir = validate_basename(
        p.failure_zip_patch_dir,
        "failure_zip_patch_dir",
    )
