from __future__ import annotations

import argparse


def add_self_backup_override_args(
    parser: argparse.ArgumentParser,
    *,
    append_override: type[argparse.Action],
) -> None:
    parser.add_argument(
        "--artifacts-root",
        action=append_override,
        key="artifacts_root",
        dest="overrides",
        metavar="PATH",
    )
    parser.add_argument(
        "--self-backup-mode",
        action=append_override,
        key="self_backup_mode",
        dest="overrides",
        choices=("never", "initial_self_patch"),
    )
    parser.add_argument(
        "--self-backup-dir",
        action=append_override,
        key="self_backup_dir",
        dest="overrides",
        metavar="RELPATH",
    )
    parser.add_argument(
        "--self-backup-template",
        action=append_override,
        key="self_backup_template",
        dest="overrides",
        metavar="TEMPLATE",
    )
    parser.add_argument(
        "--self-backup-include-relpaths",
        action=append_override,
        key="self_backup_include_relpaths",
        dest="overrides",
        metavar="CSV",
    )
