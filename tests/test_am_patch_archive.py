from __future__ import annotations

import sys
from pathlib import Path


class _FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sections: list[str] = []
        self.info: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)

    def info_core(self, text: str) -> None:
        self.info.append(text)


repo_root = Path(__file__).resolve().parents[1]
scripts_dir = repo_root / "scripts"
sys.path.insert(0, str(scripts_dir))

from am_patch.archive import archive_patch  # noqa: E402


def test_archive_patch_moves_incoming_source(tmp_path: Path) -> None:
    logger = _FakeLogger()
    patch_root = tmp_path / "patches"
    source = patch_root / "incoming" / "issue_704_v1.zip"
    dest_dir = patch_root / "successful"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("patch", encoding="utf-8")

    dest = archive_patch(logger, source, dest_dir)

    assert not source.exists()
    assert dest == dest_dir / "issue_704_v1.zip"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "patch"
    assert "archived patch script (moved)" in logger.lines[-1]


def test_archive_patch_moves_non_archived_nested_source(tmp_path: Path) -> None:
    logger = _FakeLogger()
    patch_root = tmp_path / "patches"
    source = patch_root / "queue" / "ready" / "issue_704_v1.zip"
    dest_dir = patch_root / "unsuccessful"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("patch", encoding="utf-8")

    dest = archive_patch(logger, source, dest_dir)

    assert not source.exists()
    assert dest == dest_dir / "issue_704_v1.zip"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "patch"
    assert "archived patch script (moved)" in logger.lines[-1]


def test_archive_patch_copies_from_success_archive(tmp_path: Path) -> None:
    logger = _FakeLogger()
    patch_root = tmp_path / "patches"
    source = patch_root / "successful" / "issue_704_v1.zip"
    dest_dir = patch_root / "successful"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("patch", encoding="utf-8")

    dest = archive_patch(logger, source, dest_dir)

    assert source.exists()
    assert dest == dest_dir / "issue_704_v1_v2.zip"
    assert dest.exists()
    assert source.read_text(encoding="utf-8") == "patch"
    assert dest.read_text(encoding="utf-8") == "patch"
    assert "archived patch script (copied)" in logger.lines[-1]


def test_archive_patch_copies_from_unsuccessful_archive(tmp_path: Path) -> None:
    logger = _FakeLogger()
    patch_root = tmp_path / "patches"
    source = patch_root / "unsuccessful" / "issue_704_v1.zip"
    dest_dir = patch_root / "successful"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("patch", encoding="utf-8")

    dest = archive_patch(logger, source, dest_dir)

    assert source.exists()
    assert dest == dest_dir / "issue_704_v1.zip"
    assert dest.exists()
    assert source.read_text(encoding="utf-8") == "patch"
    assert dest.read_text(encoding="utf-8") == "patch"
    assert "archived patch script (copied)" in logger.lines[-1]
