from __future__ import annotations

from typing import Any

from .app_support import _ok
from .workspace_inventory import list_workspaces


def api_workspaces(self, mem_jobs: list[Any] | None = None) -> tuple[int, bytes]:
    sig, items = list_workspaces(self, mem_jobs=mem_jobs)
    return _ok({"items": items, "sig": sig})
