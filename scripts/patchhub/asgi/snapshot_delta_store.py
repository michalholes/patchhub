from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .async_jobs_runs_indexer import IndexerSnapshot


@dataclass(frozen=True)
class SnapshotRecord:
    seq: int
    jobs: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    workspaces: list[dict[str, Any]]
    header: dict[str, Any]
    sigs: dict[str, str]


def _copy_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]


def _job_key(item: dict[str, Any]) -> str:
    return str(item.get("job_id", ""))


def _run_key(item: dict[str, Any]) -> str:
    return f"{item.get('issue_id', '')}|{item.get('mtime_utc', '')}"


def _workspace_key(item: dict[str, Any]) -> str:
    return f"{item.get('issue_id', '')}|{item.get('workspace_rel_path', '')}"


def _removed_job(item: dict[str, Any]) -> dict[str, Any]:
    return {"job_id": str(item.get("job_id", ""))}


def _removed_run(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": item.get("issue_id"),
        "mtime_utc": item.get("mtime_utc"),
    }


def _removed_workspace(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": item.get("issue_id"),
        "workspace_rel_path": item.get("workspace_rel_path"),
    }


class SnapshotDeltaStore:
    def __init__(self, *, max_records: int = 64) -> None:
        self._records: deque[SnapshotRecord] = deque(maxlen=max(2, int(max_records)))

    def record_snapshot(self, snap: IndexerSnapshot) -> None:
        self._records.append(
            SnapshotRecord(
                seq=int(getattr(snap, "seq", 0) or 0),
                jobs=_copy_items(list(snap.jobs_items)),
                runs=_copy_items(list(snap.runs_items[:80])),
                workspaces=_copy_items(list(snap.workspaces_items)),
                header=dict(snap.header_body),
                sigs={
                    "jobs": str(snap.jobs_sig),
                    "runs": str(snap.runs_sig),
                    "workspaces": str(snap.workspaces_sig),
                    "header": str(snap.header_sig),
                    "snapshot": str(snap.snapshot_sig),
                },
            )
        )

    def current_seq(self) -> int:
        if not self._records:
            return 0
        return int(self._records[-1].seq)

    def build_delta(self, since_seq: int) -> dict[str, Any]:
        if not self._records:
            return {"ok": True, "resync_needed": True, "seq": 0}

        current = self._records[-1]
        if int(since_seq) == int(current.seq):
            return {
                "ok": True,
                "seq": current.seq,
                "sigs": dict(current.sigs),
                "jobs": {"added": [], "updated": [], "removed": []},
                "runs": {"added": [], "updated": [], "removed": []},
                "workspaces": {"added": [], "updated": [], "removed": []},
                "header_changed": False,
            }

        previous = None
        for rec in self._records:
            if int(rec.seq) == int(since_seq):
                previous = rec
                break
        if previous is None:
            return {"ok": True, "resync_needed": True, "seq": current.seq}

        payload = {
            "ok": True,
            "seq": current.seq,
            "sigs": dict(current.sigs),
            "jobs": self._diff(previous.jobs, current.jobs, _job_key, _removed_job),
            "runs": self._diff(previous.runs, current.runs, _run_key, _removed_run),
            "workspaces": self._diff(
                previous.workspaces,
                current.workspaces,
                _workspace_key,
                _removed_workspace,
            ),
            "header_changed": previous.header != current.header,
        }
        if previous.header != current.header:
            payload["header"] = dict(current.header)
        return payload

    def _diff(
        self,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
        key_fn: Any,
        removed_fn: Any,
    ) -> dict[str, Any]:
        before_map = {str(key_fn(item)): item for item in before}
        after_map = {str(key_fn(item)): item for item in after}
        added: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []

        for key, item in after_map.items():
            prev = before_map.get(key)
            if prev is None:
                added.append(dict(item))
            elif prev != item:
                updated.append(dict(item))

        for key, item in before_map.items():
            if key not in after_map:
                removed.append(removed_fn(item))

        return {"added": added, "updated": updated, "removed": removed}
