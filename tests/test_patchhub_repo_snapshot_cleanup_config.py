from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.patchhub.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = REPO_ROOT / "scripts" / "patchhub" / "patchhub.toml"


def _config_text(cleanup_block: str) -> str:
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"\[repo_snapshot_cleanup\][\s\S]*?\n\[ui\]\n")
    match = pattern.search(text)
    assert match is not None
    replacement = cleanup_block.strip() + "\n\n[ui]\n"
    return text[: match.start()] + replacement + text[match.end() :]


def _write_config(tmp_path: Path, cleanup_block: str) -> Path:
    path = tmp_path / "patchhub.toml"
    path.write_text(_config_text(cleanup_block), encoding="utf-8")
    return path


def test_valid_cleanup_config_parse(tmp_path: Path) -> None:
    cfg = load_config(
        _write_config(
            tmp_path,
            """
[repo_snapshot_cleanup]

[[repo_snapshot_cleanup.rules]]
filename_pattern = "patchhub-main_*.zip"
keep_count = 3

[[repo_snapshot_cleanup.rules]]
filename_pattern = "audiomason2-main_*.zip"
keep_count = 1
""",
        )
    )
    assert cfg.repo_snapshot_cleanup.rules[0].filename_pattern == "patchhub-main_*.zip"
    assert cfg.repo_snapshot_cleanup.rules[0].keep_count == 3
    assert cfg.repo_snapshot_cleanup.rules[1].filename_pattern == "audiomason2-main_*.zip"
    assert cfg.repo_snapshot_cleanup.rules[1].keep_count == 1


@pytest.mark.parametrize(
    ("cleanup_block", "expected"),
    [
        (
            """
[repo_snapshot_cleanup]

[[repo_snapshot_cleanup.rules]]
filename_pattern = "nested/path.zip"
keep_count = 1
""",
            "must not contain separators",
        ),
        (
            '''
[repo_snapshot_cleanup]

[[repo_snapshot_cleanup.rules]]
filename_pattern = """line
wrap.zip"""
keep_count = 1
''',
            "must be single-line",
        ),
    ],
)
def test_invalid_cleanup_pattern_raises(tmp_path: Path, cleanup_block: str, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        load_config(_write_config(tmp_path, cleanup_block))


@pytest.mark.parametrize(
    ("cleanup_block", "expected"),
    [
        (
            """
[repo_snapshot_cleanup]

[[repo_snapshot_cleanup.rules]]
filename_pattern = "patchhub-main_*.zip"
keep_count = "2"
""",
            "keep_count must be an integer",
        ),
        (
            """
[repo_snapshot_cleanup]

[[repo_snapshot_cleanup.rules]]
filename_pattern = "patchhub-main_*.zip"
keep_count = -1
""",
            "keep_count must be >= 0",
        ),
    ],
)
def test_invalid_keep_count_raises(tmp_path: Path, cleanup_block: str, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        load_config(_write_config(tmp_path, cleanup_block))


def test_valid_age_cleanup_config_parse(tmp_path: Path) -> None:
    cfg = load_config(
        _write_config(
            tmp_path,
            """
[repo_snapshot_cleanup]
age_max_days = 14
age_directories = ["logs", "successful"]

[[repo_snapshot_cleanup.rules]]
filename_pattern = "badguys_*.log"
keep_count = 1
""",
        )
    )
    assert cfg.repo_snapshot_cleanup.age_max_days == 14
    assert cfg.repo_snapshot_cleanup.age_directories == ("logs", "successful")


@pytest.mark.parametrize(
    ("cleanup_block", "expected"),
    [
        (
            """
[repo_snapshot_cleanup]
age_max_days = 14
""",
            "must be provided together",
        ),
        (
            """
[repo_snapshot_cleanup]
age_directories = ["logs"]
""",
            "must be provided together",
        ),
        (
            """
[repo_snapshot_cleanup]
age_max_days = 0
age_directories = ["logs"]
""",
            "must be >= 1",
        ),
        (
            """
[repo_snapshot_cleanup]
age_max_days = 14
age_directories = ["logs", "logs"]
""",
            "duplicate entry",
        ),
        (
            """
[repo_snapshot_cleanup]
age_max_days = 14
age_directories = ["incoming"]
""",
            "unsupported value",
        ),
    ],
)
def test_invalid_age_cleanup_config_raises(
    tmp_path: Path,
    cleanup_block: str,
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        load_config(_write_config(tmp_path, cleanup_block))


def test_missing_or_empty_cleanup_rules_is_no_op(tmp_path: Path) -> None:
    missing_cfg = load_config(_write_config(tmp_path, ""))
    assert missing_cfg.repo_snapshot_cleanup.rules == ()

    empty_cfg = load_config(
        _write_config(
            tmp_path,
            """
[repo_snapshot_cleanup]
""",
        )
    )
    assert empty_cfg.repo_snapshot_cleanup.rules == ()
