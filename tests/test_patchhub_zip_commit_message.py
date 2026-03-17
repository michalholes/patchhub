from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from scripts.patchhub.zip_commit_message import (
    ZipCommitConfig,
    read_commit_message_from_zip_bytes,
)


def _make_zip(files: dict[str, bytes]) -> bytes:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return bio.getvalue()


def test_read_commit_message_ok_strips_one_trailing_lf() -> None:
    z = _make_zip({"COMMIT_MESSAGE.txt": b"Hello\n"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert err is None
    assert msg == "Hello"


def test_read_commit_message_ok_no_trailing_lf() -> None:
    z = _make_zip({"COMMIT_MESSAGE.txt": b"Hello"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert err is None
    assert msg == "Hello"


def test_read_commit_message_missing() -> None:
    z = _make_zip({"X.txt": b"Hello\n"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_commit_missing"


def test_read_commit_message_rejects_subdir() -> None:
    z = _make_zip({"x/COMMIT_MESSAGE.txt": b"Hello\n"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_commit_missing"


def test_read_commit_message_rejects_crlf() -> None:
    z = _make_zip({"COMMIT_MESSAGE.txt": b"Hello\r\n"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_commit_invalid_content"


def test_read_commit_message_rejects_non_ascii() -> None:
    z = _make_zip({"COMMIT_MESSAGE.txt": b"H\xc3\xa9"})
    cfg = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
    msg, err = read_commit_message_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_commit_invalid_content"
