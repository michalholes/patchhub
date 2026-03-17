from __future__ import annotations

import mimetypes
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_support import _err, _ok, read_tail
from .fs_jail import FsJailError, list_dir, safe_rename


@dataclass(frozen=True)
class FsDownloadPayload:
    filename: str
    media_type: str
    data: bytes | None = None
    path: Path | None = None


def _guess_content_type(path: Path) -> str:
    guessed, _enc = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _virtual_denied(self, rel: str) -> tuple[int, bytes] | None:
    vfs = getattr(self, "virtual_jobs_fs", None)
    if vfs is not None and vfs.is_mutable_path(rel):
        return _err("Virtual DB-backed path is read-only", status=409)
    return None


def api_fs_list(self, rel_path: str) -> tuple[int, bytes]:
    vfs = getattr(self, "virtual_jobs_fs", None)
    if vfs is not None and vfs.handles(rel_path):
        return _ok({"path": rel_path, "items": vfs.list_dir(rel_path), "virtual": True})
    try:
        path = self.jail.resolve_rel(rel_path)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not path.exists() or not path.is_dir():
        return _err("Not a directory", status=404)
    return _ok({"path": rel_path, "items": list_dir(path)})


def api_fs_stat(self, rel_path: str) -> tuple[int, bytes]:
    vfs = getattr(self, "virtual_jobs_fs", None)
    if vfs is not None and vfs.handles(rel_path):
        return _ok(vfs.json_stat_payload(rel_path))
    if rel_path == "":
        return _ok({"path": rel_path, "exists": True})
    try:
        path = self.jail.resolve_rel(rel_path)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    return _ok({"path": rel_path, "exists": path.exists()})


def api_fs_read_text(self, qs: dict[str, str]) -> tuple[int, bytes]:
    rel = str(qs.get("path", ""))
    tail_lines_s = qs.get("tail_lines", "")
    max_bytes = max(1, min(int(qs.get("max_bytes", "200000")), 2000000))
    vfs = getattr(self, "virtual_jobs_fs", None)
    if vfs is not None and vfs.handles(rel):
        tail_lines = int(tail_lines_s) if tail_lines_s else None
        text = vfs.read_text(rel, tail_lines=tail_lines, max_bytes=max_bytes)
        if text is None:
            return _err("Not a file", status=404)
        return _ok({"path": rel, "text": text, "truncated": False, "virtual": True})
    try:
        path = self.jail.resolve_rel(rel)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not path.exists() or not path.is_file():
        return _err("Not a file", status=404)

    if tail_lines_s:
        text = read_tail(
            path,
            int(tail_lines_s),
            max_bytes=self.cfg.server.tail_max_bytes,
            cache_max_entries=self.cfg.server.tail_cache_max_entries,
        )
        return _ok({"path": rel, "text": text, "truncated": False})

    try:
        data = path.read_bytes()
    except Exception:
        return _err("Read failed", status=500)
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    return _ok({"path": rel, "text": text, "truncated": truncated})


def api_fs_download(self, rel_path: str) -> tuple[int, bytes] | FsDownloadPayload:
    vfs = getattr(self, "virtual_jobs_fs", None)
    if vfs is not None and vfs.handles(rel_path):
        download = vfs.download(rel_path)
        if download is None:
            return _err("Not found", status=404)
        return FsDownloadPayload(
            filename=download.filename,
            media_type=download.media_type,
            data=download.data,
        )
    try:
        path = self.jail.resolve_rel(rel_path)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not path.exists() or not path.is_file():
        return _err("Not found", status=404)
    return FsDownloadPayload(
        filename=path.name,
        media_type=_guess_content_type(path),
        path=path,
    )


def api_fs_mkdir(self, body: dict[str, Any]) -> tuple[int, bytes]:
    rel = str(body.get("path", ""))
    denied = _virtual_denied(self, rel)
    if denied is not None:
        return denied
    try:
        self.jail.assert_crud_allowed(rel)
        path = self.jail.resolve_rel(rel)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    path.mkdir(parents=True, exist_ok=True)
    return _ok({"path": rel})


def api_fs_rename(self, body: dict[str, Any]) -> tuple[int, bytes]:
    src_rel = str(body.get("src", ""))
    dst_rel = str(body.get("dst", ""))
    denied = _virtual_denied(self, src_rel) or _virtual_denied(self, dst_rel)
    if denied is not None:
        return denied
    try:
        self.jail.assert_crud_allowed(src_rel)
        self.jail.assert_crud_allowed(dst_rel)
        src = self.jail.resolve_rel(src_rel)
        dst = self.jail.resolve_rel(dst_rel)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not src.exists():
        return _err("Source not found", status=404)
    safe_rename(src, dst)
    return _ok({"src": src_rel, "dst": dst_rel})


def api_fs_delete(self, body: dict[str, Any]) -> tuple[int, bytes]:
    rel = str(body.get("path", ""))
    denied = _virtual_denied(self, rel)
    if denied is not None:
        return denied
    try:
        self.jail.assert_crud_allowed(rel)
        path = self.jail.resolve_rel(rel)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not path.exists():
        return _ok({"path": rel, "deleted": False})
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return _ok({"path": rel, "deleted": True})


def api_fs_unzip(self, body: dict[str, Any]) -> tuple[int, bytes]:
    zip_rel = str(body.get("zip_path", ""))
    dest_rel = str(body.get("dest_dir", ""))
    denied = _virtual_denied(self, zip_rel) or _virtual_denied(self, dest_rel)
    if denied is not None:
        return denied
    try:
        self.jail.assert_crud_allowed(zip_rel)
        self.jail.assert_crud_allowed(dest_rel)
        zip_path = self.jail.resolve_rel(zip_rel)
        dest_path = self.jail.resolve_rel(dest_rel)
    except FsJailError as exc:
        return _err(str(exc), status=400)
    if not zip_path.exists():
        return _err("Zip not found", status=404)
    dest_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_path)
    return _ok({"zip_path": zip_rel, "dest_dir": dest_rel})
