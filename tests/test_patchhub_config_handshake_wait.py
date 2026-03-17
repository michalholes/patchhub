from __future__ import annotations

import textwrap

import pytest
from scripts.patchhub.config import load_config


def _config_text(
    *, handshake_wait_s: int, post_exit_grace_s: int, terminate_grace_s: int = 3
) -> str:
    return (
        textwrap.dedent(
            f"""
        [server]
        host = "127.0.0.1"
        port = 8099

        [meta]
        version = "test"

        [runner]
        command = ["python3", "scripts/am_patch.py"]
        default_verbosity = "normal"
        queue_enabled = true
        runner_config_toml = "scripts/am_patch/am_patch.toml"
        ipc_handshake_wait_s = {handshake_wait_s}
        post_exit_grace_s = {post_exit_grace_s}
        terminate_grace_s = {terminate_grace_s}

        [paths]
        patches_root = "patches"
        upload_dir = "patches/incoming"
        allow_crud = true
        crud_allowlist = [""]

        [upload]
        max_bytes = 200000000
        allowed_extensions = [".zip"]
        ascii_only_names = true

        [issue]
        default_regex = 'issue_(\\d+)'
        allocation_start = 1
        allocation_max = 99999

        [indexing]
        log_filename_regex = 'am_patch_issue_(\\d+)_'
        stats_windows_days = [7, 30]

        [ui]
        base_font_px = 24

        [autofill]
        enabled = true
        poll_interval_seconds = 10
        scan_dir = "patches"
        scan_extensions = [".zip"]
        scan_ignore_filenames = []
        scan_ignore_prefixes = []
        choose_strategy = "mtime_ns"
        tiebreaker = "lex_name"
        derive_enabled = true
        issue_regex = '^issue_(\\d+)_'
        commit_regex = '^issue_\\d+_(.+)\\.zip$'
        commit_replace_underscores = true
        commit_replace_dashes = true
        commit_collapse_spaces = true
        commit_trim = true
        commit_ascii_only = true
        issue_default_if_no_match = ""
        commit_default_if_no_match = ""
        overwrite_policy = "if_not_dirty"
        fill_patch_path = true
        fill_issue_id = true
        fill_commit_message = true
        zip_commit_enabled = true
        zip_commit_filename = "COMMIT_MESSAGE.txt"
        zip_commit_max_bytes = 4096
        zip_commit_max_ratio = 200
        zip_issue_enabled = true
        zip_issue_filename = "ISSUE_NUMBER.txt"
        zip_issue_max_bytes = 128
        zip_issue_max_ratio = 200
        """
        ).strip()
        + "\n"
    )


def test_load_config_rejects_non_positive_ipc_handshake_wait(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=0, post_exit_grace_s=1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"runner\.ipc_handshake_wait_s"):
        load_config(cfg_path)


def test_load_config_accepts_positive_ipc_handshake_wait(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=2, post_exit_grace_s=2),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)

    assert cfg.runner.ipc_handshake_wait_s == 2


def test_load_config_rejects_non_positive_post_exit_grace(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=1, post_exit_grace_s=0),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"runner\.post_exit_grace_s"):
        load_config(cfg_path)


def test_load_config_accepts_positive_post_exit_grace(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=2, post_exit_grace_s=2),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)

    assert cfg.runner.post_exit_grace_s == 2


def test_load_config_rejects_non_positive_terminate_grace(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=1, post_exit_grace_s=1, terminate_grace_s=0),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"runner\.terminate_grace_s"):
        load_config(cfg_path)


def test_load_config_accepts_positive_terminate_grace(tmp_path) -> None:
    cfg_path = tmp_path / "patchhub.toml"
    cfg_path.write_text(
        _config_text(handshake_wait_s=2, post_exit_grace_s=2, terminate_grace_s=4),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)

    assert cfg.runner.terminate_grace_s == 4
