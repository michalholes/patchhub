from __future__ import annotations

import argparse


def add_artifact_override_args(
    parser: argparse.ArgumentParser,
    *,
    append_override: type[argparse.Action],
) -> None:
    parser.add_argument(
        "--failure-zip",
        action=append_override,
        key="failure_zip_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--no-failure-zip",
        action=append_override,
        key="failure_zip_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--patch-script-archive",
        action=append_override,
        key="patch_script_archive_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--no-patch-script-archive",
        action=append_override,
        key="patch_script_archive_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--failure-zip-name",
        action=append_override,
        key="failure_zip_name",
        dest="overrides",
    )
    parser.add_argument(
        "--failure-zip-log-dir",
        action=append_override,
        key="failure_zip_log_dir",
        dest="overrides",
    )
    parser.add_argument(
        "--failure-zip-patch-dir",
        action=append_override,
        key="failure_zip_patch_dir",
        dest="overrides",
    )

    parser.add_argument(
        "--success-archive",
        action=append_override,
        key="success_archive_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--no-success-archive",
        action=append_override,
        key="success_archive_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--artifact-stage",
        action=append_override,
        key="artifact_stage_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--no-artifact-stage",
        action=append_override,
        key="artifact_stage_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--success-archive-name",
        dest="success_archive_name",
        default=None,
        help=("Success archive zip name template (placeholders: {repo}, {branch}, {issue}, {ts})."),
    )
    parser.add_argument(
        "--success-archive-dir",
        dest="overrides",
        action=append_override,
        key="success_archive_dir",
        help="Success archive destination: patch_dir|successful_dir.",
    )
    parser.add_argument(
        "--success-archive-cleanup-glob",
        dest="overrides",
        action=append_override,
        key="success_archive_cleanup_glob_template",
        help="Glob template for success archive retention candidate selection.",
    )
    parser.add_argument(
        "--success-archive-keep-count",
        dest="overrides",
        action=append_override,
        key="success_archive_keep_count",
        help=("Keep the last N success archives matching the glob template (0=disabled)."),
    )

    parser.add_argument(
        "--issue-diff-bundle",
        action=append_override,
        key="issue_diff_bundle_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    parser.add_argument(
        "--no-issue-diff-bundle",
        action=append_override,
        key="issue_diff_bundle_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
