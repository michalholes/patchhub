from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .web_jobs_db import VirtualEntry, WebJobsDatabase

_BASE = PurePosixPath("artifacts/web_jobs")


@dataclass(frozen=True)
class VirtualDownload:
    data: bytes
    media_type: str
    filename: str


class WebJobsVirtualFs:
    def __init__(self, *, db: WebJobsDatabase, enabled: bool) -> None:
        self._db = db
        self._enabled = bool(enabled)

    def enabled(self) -> bool:
        return self._enabled

    def _parts(self, rel_path: str) -> tuple[str, ...]:
        raw = str(rel_path or "").strip().strip("/")
        if not raw:
            return ()
        return tuple(part for part in PurePosixPath(raw).parts if part not in {".", ""})

    def handles(self, rel_path: str) -> bool:
        if not self._enabled:
            return False
        parts = self._parts(rel_path)
        if not parts:
            return False
        if parts == ("artifacts",):
            return True
        return parts[:2] == _BASE.parts

    def is_mutable_path(self, rel_path: str) -> bool:
        return self.handles(rel_path)

    def _entry_for_parts(self, parts: tuple[str, ...]) -> VirtualEntry:
        if parts == ("artifacts",):
            return VirtualEntry(rel_path="artifacts", is_dir=True, exists=True)
        if parts == _BASE.parts:
            return VirtualEntry(rel_path=str(_BASE), is_dir=True, exists=True)
        if len(parts) == 3 and parts[:2] == _BASE.parts:
            job = self._db.load_job_json(parts[2])
            return VirtualEntry(
                rel_path="/".join(parts),
                is_dir=True,
                exists=job is not None,
            )
        if len(parts) != 4 or parts[:2] != _BASE.parts:
            return VirtualEntry(rel_path="/".join(parts), is_dir=False, exists=False)
        job_id = parts[2]
        if self._db.load_job_json(job_id) is None:
            return VirtualEntry(rel_path="/".join(parts), is_dir=False, exists=False)
        text = self.read_text("/".join(parts))
        if text is None:
            return VirtualEntry(rel_path="/".join(parts), is_dir=False, exists=False)
        return VirtualEntry(
            rel_path="/".join(parts),
            is_dir=False,
            exists=True,
            size=len(text.encode("utf-8")),
            mtime_unix_ms=0,
        )

    def stat(self, rel_path: str) -> VirtualEntry:
        return self._entry_for_parts(self._parts(rel_path))

    def list_dir(self, rel_path: str) -> list[dict[str, Any]]:
        parts = self._parts(rel_path)
        if parts == ("artifacts",):
            return [{"name": "web_jobs", "is_dir": True}]
        if parts == _BASE.parts:
            return [
                {"name": job_id, "is_dir": True} for job_id in self._db.list_job_ids(limit=10000)
            ]
        if len(parts) == 3 and parts[:2] == _BASE.parts:
            job_id = parts[2]
            job = self._db.load_job_json(job_id)
            if job is None:
                return []
            event_name = self._db.legacy_event_filename(job_id)
            return [
                {"name": "job.json", "is_dir": False},
                {"name": "runner.log", "is_dir": False},
                {"name": event_name, "is_dir": False},
            ]
        return []

    def read_text(
        self,
        rel_path: str,
        *,
        tail_lines: int | None = None,
        max_bytes: int = 2_000_000,
    ) -> str | None:
        parts = self._parts(rel_path)
        if len(parts) != 4 or parts[:2] != _BASE.parts:
            return None
        job_id = parts[2]
        name = parts[3]
        if name == "job.json":
            return self._db.legacy_job_json_text(job_id)
        if name == "runner.log":
            if tail_lines is not None:
                return self._db.read_log_tail(job_id, lines=tail_lines)
            text = self._db.read_full_log(job_id)
            return text[:max_bytes]
        if name == self._db.legacy_event_filename(job_id):
            if tail_lines is not None:
                return self._db.read_effective_event_tail_text(job_id, lines=tail_lines)
            text = self._db.read_effective_event_text(job_id)
            return text[:max_bytes]
        return None

    def download(self, rel_path: str) -> VirtualDownload | None:
        text = self.read_text(rel_path)
        if text is None:
            return None
        name = self._parts(rel_path)[-1]
        media_type = "application/json" if name.endswith(".json") else "text/plain"
        return VirtualDownload(
            data=text.encode("utf-8"),
            media_type=media_type,
            filename=name,
        )

    def json_stat_payload(self, rel_path: str) -> dict[str, Any]:
        entry = self.stat(rel_path)
        return {
            "path": str(rel_path),
            "exists": bool(entry.exists),
            "is_dir": bool(entry.is_dir),
            "size": int(entry.size),
            "virtual": True,
        }
