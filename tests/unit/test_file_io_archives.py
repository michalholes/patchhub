"""Unit tests for file_io ArchiveService."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from plugins.file_io.service import (
    ArchiveFormat,
    ArchiveService,
    CollisionPolicy,
    FileService,
    RootName,
)


@pytest.fixture()
def service(tmp_path: Path) -> FileService:
    roots = {
        RootName.INBOX: tmp_path / "inbox",
        RootName.STAGE: tmp_path / "stage",
        RootName.JOBS: tmp_path / "jobs",
        RootName.OUTBOX: tmp_path / "outbox",
    }
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=True)
    return FileService(roots)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def test_pack_zip_deterministic(service: FileService) -> None:
    svc = ArchiveService(service)

    service.mkdir(RootName.INBOX, "src")
    with service.open_write(RootName.INBOX, "src/a.txt") as f:
        f.write(b"a")
    with service.open_write(RootName.INBOX, "src/b.txt") as f:
        f.write(b"b")

    svc.pack(
        RootName.INBOX,
        "src",
        RootName.OUTBOX,
        "a1.zip",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=True,
    )
    h1 = _sha256(service.resolve_abs_path(RootName.OUTBOX, "a1.zip"))

    svc.pack(
        RootName.INBOX,
        "src",
        RootName.OUTBOX,
        "a2.zip",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=True,
    )
    h2 = _sha256(service.resolve_abs_path(RootName.OUTBOX, "a2.zip"))

    assert h1 == h2


def test_unpack_flatten_collision_rename(service: FileService) -> None:
    svc = ArchiveService(service)

    # Create a zip with two different paths but same basename.
    src_dir = service.resolve_abs_path(RootName.INBOX, "src")
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "a").mkdir()
    (src_dir / "b").mkdir()
    (src_dir / "a" / "x.txt").write_bytes(b"1")
    (src_dir / "b" / "x.txt").write_bytes(b"2")

    svc.pack(
        RootName.INBOX,
        "src",
        RootName.OUTBOX,
        "c.zip",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=True,
    )

    svc.unpack(
        RootName.OUTBOX,
        "c.zip",
        RootName.STAGE,
        "dst",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=False,
        flatten=True,
        collision=CollisionPolicy.RENAME,
    )

    dst = service.resolve_abs_path(RootName.STAGE, "dst")
    files = sorted([p.name for p in dst.iterdir() if p.is_file()])
    assert files == ["x.txt", "x__1.txt"]


def test_detect_format_uses_magic_when_suffix_missing(service: FileService) -> None:
    svc = ArchiveService(service)

    service.mkdir(RootName.INBOX, "src")
    with service.open_write(RootName.INBOX, "src/a.txt") as f:
        f.write(b"a")

    svc.pack(
        RootName.INBOX,
        "src",
        RootName.OUTBOX,
        "bundle.zip",
        fmt=ArchiveFormat.ZIP,
        preserve_tree=True,
    )

    original = service.resolve_abs_path(RootName.OUTBOX, "bundle.zip")
    with service.open_read(RootName.OUTBOX, "bundle.zip") as f:
        data = f.read()
    with service.open_write(RootName.OUTBOX, "bundle.bin", overwrite=True) as f:
        f.write(data)

    detected = svc.detect_format(RootName.OUTBOX, "bundle.bin")

    assert detected.format == ArchiveFormat.ZIP
    assert original.exists()
