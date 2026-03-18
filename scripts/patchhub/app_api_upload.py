from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .app_support import _err, _is_ascii, _ok
from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    read_commit_message_from_zip_bytes,
    read_issue_number_from_zip_bytes,
)


def api_upload_patch(self, filename: str, data: bytes) -> tuple[int, bytes]:
    status_msgs: list[str] = []
    if self.cfg.upload.ascii_only_names and not _is_ascii(filename):
        return _err("Filename must be ASCII", status=400)
    if len(data) > self.cfg.upload.max_bytes:
        return _err("File too large", status=413)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in self.cfg.upload.allowed_extensions:
        return _err("File extension not allowed", status=400)

    upload_rel = self.cfg.paths.upload_dir
    prefix = self.cfg.paths.patches_root.rstrip("/")
    if upload_rel == prefix:
        rel = ""
    elif upload_rel.startswith(prefix + "/"):
        rel = upload_rel[len(prefix) + 1 :]
    else:
        return _err("upload_dir must be under patches_root", status=500)

    upload_dir = self.jail.resolve_rel(rel)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dst = upload_dir / os.path.basename(filename)
    dst.write_bytes(data)

    rel = str(Path(self.cfg.paths.upload_dir) / dst.name)
    status_msgs.append(f"upload: stored {rel} ({len(data)} bytes)")

    issue_id, commit_msg = self._derive_from_filename(dst.name)
    if ext == ".zip" and self.cfg.autofill.zip_commit_enabled:
        zcfg = ZipCommitConfig(
            enabled=True,
            filename=self.cfg.autofill.zip_commit_filename,
            max_bytes=self.cfg.autofill.zip_commit_max_bytes,
            max_ratio=self.cfg.autofill.zip_commit_max_ratio,
        )
        zmsg, _zerr = read_commit_message_from_zip_bytes(data, zcfg)
        if zmsg is not None:
            commit_msg = zmsg
            status_msgs.append(f"autofill: commit from zip {self.cfg.autofill.zip_commit_filename}")
    if ext == ".zip" and self.cfg.autofill.zip_issue_enabled:
        zicfg = ZipIssueConfig(
            enabled=True,
            filename=self.cfg.autofill.zip_issue_filename,
            max_bytes=self.cfg.autofill.zip_issue_max_bytes,
            max_ratio=self.cfg.autofill.zip_issue_max_ratio,
        )
        zid, _zerr = read_issue_number_from_zip_bytes(data, zicfg)
        if zid is not None:
            issue_id = zid
            status_msgs.append(f"autofill: issue from zip {self.cfg.autofill.zip_issue_filename}")
    payload: dict[str, Any] = {"stored_rel_path": rel, "bytes": len(data)}
    if self.cfg.autofill.derive_enabled:
        payload["derived_issue"] = issue_id
        payload["derived_commit_message"] = commit_msg
        if issue_id:
            status_msgs.append(f"autofill: derived issue={issue_id}")
    payload["status"] = status_msgs
    return _ok(payload)


# ---------------- UI pages ----------------
