from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True)
class ZipCommitConfig:
    enabled: bool
    filename: str
    max_bytes: int
    max_ratio: int


@dataclass(frozen=True)
class ZipIssueConfig:
    enabled: bool
    filename: str
    max_bytes: int
    max_ratio: int


def _strip_one_trailing_lf(s: str) -> str:
    if s.endswith("\n"):
        return s[:-1]
    return s


def _is_ascii_bytes(data: bytes) -> bool:
    return all(b < 128 for b in data)


def _validate_text_bytes(raw: bytes) -> str | None:
    if not _is_ascii_bytes(raw):
        return None
    if b"\r" in raw:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    text = _strip_one_trailing_lf(text)
    if not text:
        return None
    return text


def read_issue_number_from_zip_bytes(
    data: bytes,
    cfg: ZipIssueConfig,
) -> tuple[str | None, str | None]:
    if not cfg.enabled:
        return None, "zip_issue_disabled"
    if not cfg.filename or cfg.filename.strip() != cfg.filename:
        return None, "zip_issue_invalid_filename"
    if cfg.max_bytes <= 0:
        return None, "zip_issue_invalid_max_bytes"
    if cfg.max_ratio <= 0:
        return None, "zip_issue_invalid_max_ratio"

    try:
        with ZipFile(BytesIO(data), "r") as zf:
            target = None
            for info in zf.infolist():
                if info.filename == cfg.filename:
                    target = info
                    break
            if target is None:
                return None, "zip_issue_missing"
            # Root only: no slashes.
            if "/" in target.filename or "\\" in target.filename:
                return None, "zip_issue_not_root"
            if target.file_size > cfg.max_bytes:
                return None, "zip_issue_too_large"
            if target.compress_size and target.compress_size > 0:
                ratio = int(target.file_size // max(1, target.compress_size))
                if ratio > cfg.max_ratio:
                    return None, "zip_issue_suspicious_ratio"
            raw = zf.read(target)
    except BadZipFile:
        return None, "zip_issue_bad_zip"
    except Exception:
        return None, "zip_issue_error"

    text = _validate_text_bytes(raw)
    if text is None or not text.isdigit():
        return None, "zip_issue_invalid_content"
    return text, None


def read_issue_number_from_zip_path(
    path: Path,
    cfg: ZipIssueConfig,
) -> tuple[str | None, str | None]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, "zip_issue_read_failed"
    return read_issue_number_from_zip_bytes(data, cfg)


def read_commit_message_from_zip_bytes(
    data: bytes,
    cfg: ZipCommitConfig,
) -> tuple[str | None, str | None]:
    if not cfg.enabled:
        return None, "zip_commit_disabled"
    if not cfg.filename or cfg.filename.strip() != cfg.filename:
        return None, "zip_commit_invalid_filename"
    if cfg.max_bytes <= 0:
        return None, "zip_commit_invalid_max_bytes"
    if cfg.max_ratio <= 0:
        return None, "zip_commit_invalid_max_ratio"

    try:
        with ZipFile(BytesIO(data), "r") as zf:
            target = None
            for info in zf.infolist():
                if info.filename == cfg.filename:
                    target = info
                    break
            if target is None:
                return None, "zip_commit_missing"
            # Root only: no slashes.
            if "/" in target.filename or "\\" in target.filename:
                return None, "zip_commit_not_root"
            if target.file_size > cfg.max_bytes:
                return None, "zip_commit_too_large"
            if target.compress_size and target.compress_size > 0:
                ratio = int(target.file_size // max(1, target.compress_size))
                if ratio > cfg.max_ratio:
                    return None, "zip_commit_suspicious_ratio"
            raw = zf.read(target)
    except BadZipFile:
        return None, "zip_commit_bad_zip"
    except Exception:
        return None, "zip_commit_error"

    text = _validate_text_bytes(raw)
    if text is None:
        return None, "zip_commit_invalid_content"
    return text, None


def read_commit_message_from_zip_path(
    path: Path,
    cfg: ZipCommitConfig,
) -> tuple[str | None, str | None]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, "zip_commit_read_failed"
    return read_commit_message_from_zip_bytes(data, cfg)


def zip_contains_patch_file(path: Path) -> tuple[bool, str | None]:
    """Return whether the given zip contains any file entry ending with .patch.

    Contract:
    - (True, None) if a .patch file entry exists anywhere in the zip (case-insensitive)
    - (False, "no_patch") if the zip is readable but contains no .patch file entries
    - (False, "bad_zip") for BadZipFile
    - (False, "zip_error") for other read/open errors

    Notes:
    - Directory entries are ignored.
    - Member content is never read; only the central directory is inspected.
    """

    try:
        with ZipFile(path, "r") as zf:
            for info in zf.infolist():
                try:
                    if info.is_dir():
                        continue
                except Exception:
                    if str(info.filename).endswith("/"):
                        continue
                name = str(info.filename)
                if name.lower().endswith(".patch"):
                    return True, None
            return False, "no_patch"
    except BadZipFile:
        return False, "bad_zip"
    except Exception:
        return False, "zip_error"
