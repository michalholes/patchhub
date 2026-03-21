from __future__ import annotations

import sys
from pathlib import Path


def _import_help_text():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.cli_help_text import fmt_full_help, fmt_short_help

    return fmt_full_help, fmt_short_help


def test_short_help_mentions_finalize_from_cwd_and_default_message() -> None:
    _, fmt_short_help = _import_help_text()
    text = fmt_short_help("test")

    assert "-s, --finalize-live-from-cwd [MESSAGE]" in text
    assert 'When MESSAGE is omitted, commit message defaults to "finalize".' in text


def test_full_help_mentions_finalize_from_cwd_and_default_message() -> None:
    fmt_full_help, _ = _import_help_text()
    text = fmt_full_help("test")

    assert "--finalize-live-from-cwd [MESSAGE] (-s)" in text
    assert 'When MESSAGE is omitted, commit message defaults to "finalize".' in text


def test_full_help_mentions_self_backup_flags() -> None:
    fmt_full_help, _ = _import_help_text()
    text = fmt_full_help("test")

    assert "--artifacts-root PATH" in text
    assert "--self-backup-mode {never,initial_self_patch}" in text
    assert "--self-backup-dir RELPATH" in text
    assert "--self-backup-template TEMPLATE" in text
    assert "--self-backup-include-relpaths CSV" in text
