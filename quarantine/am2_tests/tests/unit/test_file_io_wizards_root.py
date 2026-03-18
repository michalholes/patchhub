"""Unit tests for the file_io WIZARDS root.

Covers:
- RootName.WIZARDS is defined.
- FileService enforces jail semantics for the WIZARDS root.
- ArchiveService can pack/unpack using the WIZARDS root.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.file_io.service import ArchiveFormat, ArchiveService, FileService, RootName
from plugins.file_io.service.paths import InvalidRelativePathError


@pytest.fixture()
def service(tmp_path: Path) -> FileService:
    roots = {
        RootName.INBOX: tmp_path / "inbox",
        RootName.STAGE: tmp_path / "stage",
        RootName.JOBS: tmp_path / "jobs",
        RootName.OUTBOX: tmp_path / "outbox",
        RootName.WIZARDS: tmp_path / "wizards",
    }
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=True)
    return FileService(roots)


def test_wizards_root_defined() -> None:
    assert RootName.WIZARDS.value == "wizards"


def test_wizards_root_jail_enforced(service: FileService) -> None:
    with pytest.raises(InvalidRelativePathError):
        service.resolve_abs_path(RootName.WIZARDS, "../escape.txt")


def test_archive_pack_unpack_roundtrip_in_wizards_root(
    service: FileService, tmp_path: Path
) -> None:
    svc = ArchiveService(service)
    # Create a small directory tree under wizards
    service.mkdir(RootName.WIZARDS, "src", parents=True)
    with service.open_write(RootName.WIZARDS, "src/a.txt") as f:
        f.write(b"a")
    with service.open_write(RootName.WIZARDS, "src/nested/b.txt") as f:
        f.write(b"b")

    # Pack to a zip archive in wizards
    svc.pack(
        src_root=RootName.WIZARDS,
        src_dir="src",
        dst_root=RootName.WIZARDS,
        dst_archive_path="bundle.zip",
        fmt=ArchiveFormat.ZIP,
        autodetect=False,
        preserve_tree=True,
        flatten=False,
    )
    assert service.exists(RootName.WIZARDS, "bundle.zip")

    # Unpack to dst directory in wizards
    svc.unpack(
        src_root=RootName.WIZARDS,
        src_archive_path="bundle.zip",
        dst_root=RootName.WIZARDS,
        dst_dir="dst",
        fmt=ArchiveFormat.ZIP,
        autodetect=False,
        preserve_tree=True,
        flatten=False,
    )
    assert service.exists(RootName.WIZARDS, "dst/a.txt")
    assert service.exists(RootName.WIZARDS, "dst/nested/b.txt")
