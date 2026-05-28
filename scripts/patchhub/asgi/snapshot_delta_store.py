from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .async_jobs_runs_indexer import IndexerSnapshot


@dataclass(frozen=True)
class SnapshotRecord:
    seq: int
    jobs: list[dict[str, object]]
    runs: list[dict[str, object]]
    patches: list[dict[str, object]]
    workspaces: list[dict[str, object]]
    header: dict[str, object]
    operator_info: dict[str, object]
    sigs: dict[str, str]


def _copy_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(item) for item in items]


def _job_key(item: dict[str, object]) -> str:
    return str(item.get("job_id", ""))


def _run_key(item: dict[str, object]) -> str:
    return f"{item.get('issue_id', '')}|{item.get('mtime_utc', '')}"


def _workspace_key(item: dict[str, object]) -> str:
    return f"{item.get('issue_id', '')}|{item.get('workspace_rel_path', '')}"


def _removed_job(item: dict[str, object]) -> dict[str, object]:
    return {"job_id": str(item.get("job_id", ""))}


def _removed_run(item: dict[str, object]) -> dict[str, object]:
    return {
        "issue_id": item.get("issue_id"),
        "mtime_utc": item.get("mtime_utc"),
    }


def _removed_workspace(item: dict[str, object]) -> dict[str, object]:
    return {
        "issue_id": item.get("issue_id"),
        "workspace_rel_path": item.get("workspace_rel_path"),
    }


def _patch_key(item: dict[str, object]) -> str:
    return str(item.get("stored_rel_path", ""))


def _removed_patch(item: dict[str, object]) -> dict[str, object]:
    return {"stored_rel_path": item.get("stored_rel_path")}


class SnapshotDeltaStore:
    def __init__(self, *, max_records: int = 64) -> None:
        self._records: deque[SnapshotRecord] = deque(maxlen=max(2, int(max_records)))

    def record_snapshot(self, snap: IndexerSnapshot) -> None:
        self._records.append(
            SnapshotRecord(
                seq=int(snap.seq),
                jobs=_copy_items(list(snap.jobs_items)),
                runs=_copy_items(list(snap.runs_items[:80])),
                patches=_copy_items(list(snap.patches_items)),
                workspaces=_copy_items(list(snap.workspaces_items)),
                header=dict(snap.header_body),
                operator_info=dict(snap.operator_info),
                sigs={
                    "jobs": str(snap.jobs_sig),
                    "runs": str(snap.runs_sig),
                    "patches": str(snap.patches_sig),
                    "workspaces": str(snap.workspaces_sig),
                    "header": str(snap.header_sig),
                    "operator_info": str(snap.operator_info_sig),
                    "snapshot": str(snap.snapshot_sig),
                },
            )
        )

    def current_seq(self) -> int:
        if not self._records:
            return 0
        return int(self._records[-1].seq)

    def build_delta(self, since_seq: int) -> dict[str, object]:
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
                "patches": {
                    "added": [],
                    "updated": [],
                    "removed": [],
                    "ordered_keys": [_patch_key(item) for item in current.patches],
                },
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

        if previous.operator_info != current.operator_info:
            return {"ok": True, "resync_needed": True, "seq": current.seq}

        payload: dict[str, object] = {
            "ok": True,
            "seq": current.seq,
            "sigs": dict(current.sigs),
            "jobs": self._diff(previous.jobs, current.jobs, _job_key, _removed_job),
            "runs": self._diff(previous.runs, current.runs, _run_key, _removed_run),
            "patches": self._diff(
                previous.patches,
                current.patches,
                _patch_key,
                _removed_patch,
                include_order=True,
            ),
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
        before: list[dict[str, object]],
        after: list[dict[str, object]],
        key_fn: Callable[[dict[str, object]], str],
        removed_fn: Callable[[dict[str, object]], dict[str, object]],
        *,
        include_order: bool = False,
    ) -> dict[str, object]:
        before_map = {str(key_fn(item)): item for item in before}
        after_map = {str(key_fn(item)): item for item in after}
        added: list[dict[str, object]] = []
        updated: list[dict[str, object]] = []
        removed: list[dict[str, object]] = []

        for key, item in after_map.items():
            prev = before_map.get(key)
            if prev is None:
                added.append(dict(item))
            elif prev != item:
                updated.append(dict(item))

        for key, item in before_map.items():
            if key not in after_map:
                removed.append(removed_fn(item))

        payload: dict[str, object] = {"added": added, "updated": updated, "removed": removed}
        if include_order:
            payload["ordered_keys"] = [str(key_fn(item)) for item in after]
        return payload
