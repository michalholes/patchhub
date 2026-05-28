from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from patchhub.app_api_amp import runner_config_path
from patchhub.app_support import iter_canceled_runs
from patchhub.config import AppConfig
from patchhub.models import JobRecord, compute_commit_summary
from patchhub.web_jobs_db import WebJobsDatabase

_runner_config_path = runner_config_path
_iter_canceled_runs = iter_canceled_runs


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


class WorkspaceCore(Protocol):
    repo_root: Path
    cfg: AppConfig
    patches_root: Path
    jobs_root: Path
    web_jobs_db: WebJobsDatabase | None


def _runner_workspace_config(repo_root: Path, cfg: AppConfig) -> WorkspaceRuntimeConfig:
    from am_patch.config import Policy, build_policy, load_config

    cfg_path = _runner_config_path(repo_root, cfg)
    flat, ok = load_config(cfg_path)
    if not ok:
        flat = {}
    policy = build_policy(Policy(), flat)
    return WorkspaceRuntimeConfig(
        patches_root_rel=str(cfg.paths.patches_root),
        workspaces_dir_name=str(policy.patch_layout_workspaces_dir),
        issue_dir_template=str(policy.workspace_issue_dir_template),
        repo_dir_name=str(policy.workspace_repo_dir_name),
        meta_filename=str(policy.workspace_meta_filename),
    )


def _read_json_dict(path: Path) -> dict[str, object]:
    raw: object
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, Mapping):
        return {}
    mapping = cast(Mapping[object, object], raw)
    out: dict[str, object] = {}
    for key, val in mapping.items():
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
    for item in cast(list[object], allowed):
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


def _latest_known_run_result_by_issue(core: WorkspaceCore) -> dict[int, str]:
    from patchhub.indexing import iter_runs

    runs = list(iter_runs(core.patches_root, core.cfg.indexing.log_filename_regex))
    try:
        web_jobs_db = core.web_jobs_db
    except AttributeError:
        web_jobs_db = None
    if web_jobs_db is not None:
        canceled_source: WebJobsDatabase | Path = web_jobs_db
    else:
        try:
            canceled_source = core.jobs_root
        except AttributeError:
            canceled_source = core.patches_root
    runs.extend(_iter_canceled_runs(canceled_source))
    out: dict[int, tuple[str, str, str]] = {}
    for run in runs:
        issue_id = int(run.issue_id)
        cand = (str(run.mtime_utc), str(run.log_rel_path), str(run.result))
        prev = out.get(issue_id)
        if prev is None or cand[0] > prev[0] or (cand[0] == prev[0] and cand[1] > prev[1]):
            out[issue_id] = cand
    return {issue_id: result for issue_id, (_mtime, _path, result) in out.items()}


def _dirent_name(entry: os.DirEntry[str]) -> str:
    return str(entry.name)


def _busy_issue_ids(mem_jobs: list[JobRecord]) -> set[int]:
    out: set[int] = set()
    for job in mem_jobs:
        status = str(job.status)
        if status not in ("queued", "running"):
            continue
        issue_s = str(job.issue_id)
        try:
            out.add(int(issue_s))
        except Exception:
            continue
    return out


def _workspace_sort_key(item: dict[str, object]) -> tuple[str, int]:
    mtime_utc = str(item.get("mtime_utc", ""))
    issue_raw = item.get("issue_id", 0)
    if isinstance(issue_raw, bool):
        issue_id = int(issue_raw)
    elif isinstance(issue_raw, int):
        issue_id = issue_raw
    else:
        try:
            issue_id = int(str(issue_raw).strip() or "0")
        except Exception:
            issue_id = 0
    return mtime_utc, issue_id


def _workspace_mtime_utc(ws_root: Path, repo_dir: Path, meta_path: Path) -> str:
    mtimes: list[float] = []
    for cand in (ws_root, repo_dir, meta_path):
        try:
            mtimes.append(float(cand.stat().st_mtime))
        except Exception:
            continue
    return _utc_iso(max(mtimes) if mtimes else 0.0)


def list_workspaces(
    core: WorkspaceCore,
    mem_jobs: list[JobRecord] | None = None,
) -> tuple[str, list[dict[str, object]]]:
    if mem_jobs is None:
        mem_jobs = []
    runtime_cfg = _runner_workspace_config(core.repo_root, core.cfg)
    workspaces_root = core.patches_root / runtime_cfg.workspaces_root_rel
    latest_results = _latest_known_run_result_by_issue(core)
    busy_issue_ids = _busy_issue_ids(mem_jobs)

    items: list[dict[str, object]] = []
    sig_parts: list[str] = []

    try:
        entries = sorted(
            [ent for ent in os.scandir(workspaces_root) if ent.is_dir()],
            key=_dirent_name,
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
        item: dict[str, object] = {
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

    items.sort(key=_workspace_sort_key, reverse=True)

    from hashlib import sha1

    sig = "workspaces:" + sha1("\n".join(sig_parts).encode("utf-8")).hexdigest()
    return sig, items
