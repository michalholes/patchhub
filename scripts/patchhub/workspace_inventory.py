from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from patchhub.app_api_amp import _runner_config_path
from patchhub.app_support import _iter_canceled_runs, active_canceled_runs_source
from patchhub.models import compute_commit_summary


@dataclass(frozen=True)
class WorkspaceRuntimeConfig:
    patches_root_rel: str
    workspaces_dir_name: str
    issue_dir_template: str
    repo_dir_name: str
    meta_filename: str

    @property
    def workspaces_root_rel(self) -> str:
        return str(Path(self.workspaces_dir_name))


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runner_workspace_config(repo_root: Path, cfg: Any) -> WorkspaceRuntimeConfig:
    from am_patch.config import Policy, build_policy, load_config

    cfg_path = _runner_config_path(repo_root, cfg)
    flat, ok = load_config(cfg_path)
    if not ok:
        flat = {}
    policy = build_policy(Policy(), flat)
    return WorkspaceRuntimeConfig(
        patches_root_rel=str(getattr(cfg.paths, "patches_root", "patches")),
        workspaces_dir_name=str(policy.patch_layout_workspaces_dir),
        issue_dir_template=str(policy.workspace_issue_dir_template),
        repo_dir_name=str(policy.workspace_repo_dir_name),
        meta_filename=str(policy.workspace_meta_filename),
    )


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        out[str(key)] = val
    return out


def _issue_id_from_name(name: str, issue_dir_template: str) -> int | None:
    if "{issue}" not in issue_dir_template:
        return None
    prefix, suffix = issue_dir_template.split("{issue}", 1)
    if not name.startswith(prefix):
        return None
    if suffix and not name.endswith(suffix):
        return None
    body = name[len(prefix) :]
    if suffix:
        body = body[: -len(suffix)]
    if not body.isdigit():
        return None
    return int(body)


def _allowed_union_count(ws_root: Path) -> int | None:
    raw = _read_json_dict(ws_root / ".am_patch_state.json")
    allowed = raw.get("allowed_union")
    if not isinstance(allowed, list):
        return None
    count = 0
    for item in allowed:
        if isinstance(item, str):
            count += 1
    return count


def _git_dirty(repo_dir: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_dir,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    return bool((proc.stdout or "").strip())


def _latest_known_run_result_by_issue(core: Any) -> dict[int, str]:
    from patchhub.indexing import iter_runs

    runs = list(iter_runs(core.patches_root, core.cfg.indexing.log_filename_regex))
    runs.extend(_iter_canceled_runs(active_canceled_runs_source(core)))
    out: dict[int, tuple[str, str, str]] = {}
    for run in runs:
        issue_id = int(run.issue_id)
        cand = (str(run.mtime_utc), str(run.log_rel_path), str(run.result))
        prev = out.get(issue_id)
        if prev is None or cand[:2] > prev[:2]:
            out[issue_id] = cand
    return {issue_id: result for issue_id, (_mtime, _path, result) in out.items()}


def _busy_issue_ids(mem_jobs: list[Any]) -> set[int]:
    out: set[int] = set()
    for job in mem_jobs:
        status = str(getattr(job, "status", ""))
        if status not in ("queued", "running"):
            continue
        issue_s = str(getattr(job, "issue_id", ""))
        try:
            out.add(int(issue_s))
        except Exception:
            continue
    return out


def _workspace_mtime_utc(ws_root: Path, repo_dir: Path, meta_path: Path) -> str:
    mtimes: list[float] = []
    for cand in (ws_root, repo_dir, meta_path):
        try:
            mtimes.append(float(cand.stat().st_mtime))
        except Exception:
            continue
    return _utc_iso(max(mtimes) if mtimes else 0.0)


def list_workspaces(
    core: Any,
    mem_jobs: list[Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    if mem_jobs is None:
        mem_jobs = []
    runtime_cfg = _runner_workspace_config(core.repo_root, core.cfg)
    workspaces_root = core.patches_root / runtime_cfg.workspaces_root_rel
    latest_results = _latest_known_run_result_by_issue(core)
    busy_issue_ids = _busy_issue_ids(mem_jobs)

    items: list[dict[str, Any]] = []
    sig_parts: list[str] = []

    try:
        entries = sorted(
            [ent for ent in os.scandir(workspaces_root) if ent.is_dir()],
            key=lambda ent: ent.name,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        entries = []

    for ent in entries:
        issue_id = _issue_id_from_name(ent.name, runtime_cfg.issue_dir_template)
        if issue_id is None:
            continue
        ws_root = Path(ent.path)
        repo_dir = ws_root / runtime_cfg.repo_dir_name
        if not repo_dir.exists() or not repo_dir.is_dir():
            continue
        meta_path = ws_root / runtime_cfg.meta_filename
        meta = _read_json_dict(meta_path)
        attempt_raw = meta.get("attempt")
        attempt: int | None
        if isinstance(attempt_raw, bool):
            attempt = int(attempt_raw)
        elif isinstance(attempt_raw, int):
            attempt = attempt_raw
        elif isinstance(attempt_raw, str) and attempt_raw.strip().isdigit():
            attempt = int(attempt_raw.strip())
        else:
            attempt = None
        msg_any = meta.get("message")
        commit_summary = None
        if isinstance(msg_any, str) and msg_any.strip():
            commit_summary = compute_commit_summary(msg_any)
        allowed_union_count = _allowed_union_count(ws_root)
        dirty = _git_dirty(repo_dir)
        latest_result = str(latest_results.get(issue_id, ""))
        if dirty:
            state = "DIRTY"
        elif latest_result == "success":
            state = "KEPT_AFTER_SUCCESS"
        else:
            state = "CLEAN"
        busy = issue_id in busy_issue_ids
        workspace_rel_path = str(Path(runtime_cfg.workspaces_root_rel) / ent.name)
        mtime_utc = _workspace_mtime_utc(ws_root, repo_dir, meta_path)
        item = {
            "issue_id": issue_id,
            "workspace_rel_path": workspace_rel_path,
            "state": state,
            "busy": busy,
            "mtime_utc": mtime_utc,
            "attempt": attempt,
            "commit_summary": commit_summary,
            "allowed_union_count": allowed_union_count,
        }
        items.append(item)
        sig_parts.append(
            "|".join(
                [
                    str(issue_id),
                    workspace_rel_path,
                    state,
                    "1" if busy else "0",
                    mtime_utc,
                    "" if attempt is None else str(attempt),
                    "" if commit_summary is None else commit_summary,
                    "" if allowed_union_count is None else str(allowed_union_count),
                ]
            )
        )

    items.sort(key=lambda item: (str(item["mtime_utc"]), int(item["issue_id"])), reverse=True)

    from hashlib import sha1

    sig = "workspaces:" + sha1("\n".join(sig_parts).encode("utf-8")).hexdigest()
    return sig, items
