from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BackendMode = Literal["db_primary", "file_emergency", "resolving"]


@dataclass
class WebJobsBackendModeState:
    jobs_root: Path
    db_path: Path
    mode: BackendMode = "resolving"
    authoritative_backend: str = "unresolved"
    resolution_done: bool = False
    queue_writable: bool = False
    last_recovery: dict[str, Any] = field(default_factory=lambda: {"status": "not_run"})

    def begin_resolution(self) -> None:
        self.mode = "resolving"
        self.authoritative_backend = "unresolved"
        self.resolution_done = False
        self.queue_writable = False

    def activate_db_primary(self, recovery: dict[str, Any]) -> None:
        self.mode = "db_primary"
        self.authoritative_backend = "db"
        self.resolution_done = True
        self.queue_writable = True
        self.last_recovery = dict(recovery)

    def activate_file_emergency(self, recovery: dict[str, Any]) -> None:
        self.mode = "file_emergency"
        self.authoritative_backend = "files"
        self.resolution_done = True
        self.queue_writable = True
        self.last_recovery = dict(recovery)

    def queue_block_reason(self) -> str | None:
        if self.resolution_done and self.queue_writable:
            return None
        return "Backend mode selection is not finished"

    def debug_payload(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "authoritative_backend": str(self.authoritative_backend),
            "resolution_done": bool(self.resolution_done),
            "queue_writable": bool(self.queue_writable),
            "jobs_root": str(self.jobs_root),
            "db_path": str(self.db_path),
            "last_recovery": dict(self.last_recovery),
        }
