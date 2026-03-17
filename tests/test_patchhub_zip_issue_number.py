from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from scripts.patchhub.zip_commit_message import (
    ZipIssueConfig,
    read_issue_number_from_zip_bytes,
)


def _make_zip(files: dict[str, bytes]) -> bytes:
    bio = BytesIO()
    with ZipFile(bio, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return bio.getvalue()


def test_read_issue_number_ok_strips_one_trailing_lf() -> None:
    z = _make_zip({"ISSUE_NUMBER.txt": b"602\n"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert err is None
    assert msg == "602"


def test_read_issue_number_ok_no_trailing_lf() -> None:
    z = _make_zip({"ISSUE_NUMBER.txt": b"602"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert err is None
    assert msg == "602"


def test_read_issue_number_missing() -> None:
    z = _make_zip({"X.txt": b"602\n"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_issue_missing"


def test_read_issue_number_rejects_subdir() -> None:
    z = _make_zip({"x/ISSUE_NUMBER.txt": b"602\n"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_issue_missing"


def test_read_issue_number_rejects_crlf() -> None:
    z = _make_zip({"ISSUE_NUMBER.txt": b"602\r\n"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_issue_invalid_content"


def test_read_issue_number_rejects_non_ascii() -> None:
    z = _make_zip({"ISSUE_NUMBER.txt": b"60\xc3\xa2"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_issue_invalid_content"


def test_read_issue_number_rejects_non_digit() -> None:
    z = _make_zip({"ISSUE_NUMBER.txt": b"abc\n"})
    cfg = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
    msg, err = read_issue_number_from_zip_bytes(z, cfg)
    assert msg is None
    assert err == "zip_issue_invalid_content"
