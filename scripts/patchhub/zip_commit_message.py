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


@dataclass(frozen=True)
class ZipTargetConfig:
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


def _validate_target_text_bytes(raw: bytes) -> str | None:
    if not _is_ascii_bytes(raw) or b"\r" in raw:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    text = _strip_one_trailing_lf(text)
    if not text or "\n" in text:
        return None
    if "/" in text or "\\" in text:
        return None
    if any(ch.isspace() for ch in text):
        return None
    return text


def _read_root_zip_text_member(
    data: bytes,
    *,
    enabled: bool,
    filename: str,
    max_bytes: int,
    max_ratio: int,
    err_prefix: str,
) -> tuple[bytes | None, str | None]:
    if not enabled:
        return None, f"{err_prefix}_disabled"
    if not filename or filename.strip() != filename:
        return None, f"{err_prefix}_invalid_filename"
    if max_bytes <= 0:
        return None, f"{err_prefix}_invalid_max_bytes"
    if max_ratio <= 0:
        return None, f"{err_prefix}_invalid_max_ratio"
    try:
        with ZipFile(BytesIO(data), "r") as zf:
            target = None
            for info in zf.infolist():
                if info.filename == filename:
                    target = info
                    break
            if target is None:
                return None, f"{err_prefix}_missing"
            if "/" in target.filename or "\\" in target.filename:
                return None, f"{err_prefix}_not_root"
            if target.file_size > max_bytes:
                return None, f"{err_prefix}_too_large"
            if target.compress_size and target.compress_size > 0:
                ratio = int(target.file_size // max(1, target.compress_size))
                if ratio > max_ratio:
                    return None, f"{err_prefix}_suspicious_ratio"
            return zf.read(target), None
    except BadZipFile:
        return None, f"{err_prefix}_bad_zip"
    except Exception:
        return None, f"{err_prefix}_error"


def read_issue_number_from_zip_bytes(
    data: bytes,
    cfg: ZipIssueConfig,
) -> tuple[str | None, str | None]:
    raw, err = _read_root_zip_text_member(
        data,
        enabled=cfg.enabled,
        filename=cfg.filename,
        max_bytes=cfg.max_bytes,
        max_ratio=cfg.max_ratio,
        err_prefix="zip_issue",
    )
    if raw is None:
        return None, err
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
    raw, err = _read_root_zip_text_member(
        data,
        enabled=cfg.enabled,
        filename=cfg.filename,
        max_bytes=cfg.max_bytes,
        max_ratio=cfg.max_ratio,
        err_prefix="zip_commit",
    )
    if raw is None:
        return None, err
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


def read_target_repo_from_zip_bytes(
    data: bytes,
    cfg: ZipTargetConfig,
) -> tuple[str | None, str | None]:
    raw, err = _read_root_zip_text_member(
        data,
        enabled=cfg.enabled,
        filename=cfg.filename,
        max_bytes=cfg.max_bytes,
        max_ratio=cfg.max_ratio,
        err_prefix="zip_target",
    )
    if raw is None:
        return None, err
    text = _validate_target_text_bytes(raw)
    if text is None:
        return None, "zip_target_invalid_content"
    return text, None


def read_target_repo_from_zip_path(
    path: Path,
    cfg: ZipTargetConfig,
) -> tuple[str | None, str | None]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, "zip_target_read_failed"
    return read_target_repo_from_zip_bytes(data, cfg)


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
