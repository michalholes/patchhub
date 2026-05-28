from __future__ import annotations

from .app_support import _ok
from .models import JobRecord
from .workspace_inventory import WorkspaceCore, list_workspaces


def api_workspaces(
    self: WorkspaceCore,
    mem_jobs: list[JobRecord] | None = None,
) -> tuple[int, bytes]:
    sig, items = list_workspaces(self, mem_jobs=mem_jobs)
    return _ok({"items": items, "sig": sig})
