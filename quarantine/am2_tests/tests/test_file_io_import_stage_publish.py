"""Issue 124: file_io import runtime stage/publish/cleanup surfaces."""

from __future__ import annotations

from pathlib import Path

from plugins.file_io.plugin import FileIOPlugin
from plugins.file_io.service import ArchiveFormat, RootName


def _plugin(tmp_path: Path) -> FileIOPlugin:
    roots = {}
    for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards"):
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        roots[f"{name}_dir"] = str(root)
    return FileIOPlugin(config={"roots": roots})


def test_stage_publish_and_cleanup_surfaces_keep_root_relative_model(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path)
    source_dir = tmp_path / "inbox" / "Author" / "Book"
    source_dir.mkdir(parents=True)
    (source_dir / "track01.mp3").write_bytes(b"one")

    staged = plugin.stage_import_path("inbox", "Author/Book")

    assert staged == {
        "source": {"root": "inbox", "relative_path": "Author/Book"},
        "work": {
            "root": "stage",
            "relative_path": "import_runtime/work/Author/Book",
        },
        "intake": {"kind": "dir", "archive_format": ""},
    }
    staged_file = (
        tmp_path
        / "stage"
        / "import_runtime"
        / "work"
        / "Author"
        / "Book"
        / "track01.mp3"
    )
    assert staged_file.read_bytes() == b"one"

    published = plugin.publish_import_path(
        work_relative_path=staged["work"]["relative_path"],
        final_relative_path="Author/Book",
        mode="stage",
    )

    assert published == {
        "work": {
            "root": "stage",
            "relative_path": "import_runtime/work/Author/Book",
        },
        "final": {"root": "stage", "relative_path": "Author/Book"},
        "cleanup_performed": True,
    }
    assert (
        tmp_path / "stage" / "Author" / "Book" / "track01.mp3"
    ).read_bytes() == b"one"
    assert not (
        tmp_path / "stage" / "import_runtime" / "work" / "Author" / "Book"
    ).exists()


def test_stage_import_path_unpacks_archive_into_deterministic_work_tree(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path)
    source_dir = tmp_path / "inbox" / "bundle_src"
    source_dir.mkdir(parents=True)
    (source_dir / "track01.mp3").write_bytes(b"one")

    plugin.archive_service.pack(
        RootName.INBOX,
        "bundle_src",
        RootName.INBOX,
        "bundle.zip",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=True,
    )

    staged = plugin.stage_import_path("inbox", "bundle.zip")

    assert staged == {
        "source": {"root": "inbox", "relative_path": "bundle.zip"},
        "work": {"root": "stage", "relative_path": "import_runtime/work/bundle"},
        "intake": {"kind": "archive", "archive_format": "zip"},
    }
    staged_file = (
        tmp_path / "stage" / "import_runtime" / "work" / "bundle" / "track01.mp3"
    )
    assert staged_file.read_bytes() == b"one"


def test_publish_import_path_uses_deterministic_fallback_when_target_exists(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path)
    source_dir = tmp_path / "inbox" / "Author" / "Book"
    source_dir.mkdir(parents=True)
    (source_dir / "track01.mp3").write_bytes(b"v1")

    first_stage = plugin.stage_import_path("inbox", "Author/Book")
    plugin.publish_import_path(
        work_relative_path=first_stage["work"]["relative_path"],
        final_relative_path="Author/Book",
        mode="inplace",
    )

    (source_dir / "track01.mp3").write_bytes(b"v2")
    second_stage = plugin.stage_import_path("inbox", "Author/Book")
    published = plugin.publish_import_path(
        work_relative_path=second_stage["work"]["relative_path"],
        final_relative_path="Author/Book",
        mode="inplace",
        overwrite=False,
    )

    assert published["final"] == {"root": "outbox", "relative_path": "Author/Book__1"}
    assert (
        tmp_path / "outbox" / "Author" / "Book__1" / "track01.mp3"
    ).read_bytes() == b"v2"


def test_cleanup_import_path_removes_work_tree(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path)
    source_dir = tmp_path / "inbox" / "Author" / "Book"
    source_dir.mkdir(parents=True)
    (source_dir / "track01.mp3").write_bytes(b"one")

    staged = plugin.stage_import_path("inbox", "Author/Book")
    plugin.cleanup_import_path(staged["work"]["relative_path"])

    assert not (
        tmp_path / "stage" / "import_runtime" / "work" / "Author" / "Book"
    ).exists()
