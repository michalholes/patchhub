from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from . import proc_resources
from .app_support import (
    _ascii_sanitize,
    _decorate_run,
    _err,
    _iter_canceled_runs,
    _json_bytes,
    _ok,
    active_canceled_runs_source,
    canceled_runs_signature,
    compute_success_archive_rel,
    read_tail,
)
from .command_parse import CommandParseError, parse_runner_command
from .indexing import compute_stats, iter_runs, runs_signature
from .models import run_to_list_item_json
from .targeting import validate_targeting_config
from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    ZipTargetConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
    read_target_repo_from_zip_path,
    zip_contains_patch_file,
)


def _autofill_scan_dir_rel(self) -> str | None:
    scan_dir = str(self.cfg.autofill.scan_dir or "").strip().replace("\\", "/")
    scan_dir = scan_dir.lstrip("/")
    if not scan_dir:
        scan_dir = self.cfg.paths.patches_root

    prefix = self.cfg.paths.patches_root.rstrip("/")
    if scan_dir == prefix:
        return ""
    if scan_dir.startswith(prefix + "/"):
        return scan_dir[len(prefix) + 1 :]
    return None


def _targeting_default_repo(self) -> str:
    target_cfg = getattr(self.cfg, "targeting", None)
    value = str(getattr(target_cfg, "default_target_repo", "patchhub") or "").strip()
    return value or "patchhub"


def _target_options(self) -> list[str]:
    runner_cfg_path = (self.repo_root / self.cfg.runner.runner_config_toml).resolve()
    try:
        return validate_targeting_config(
            runner_config_toml=runner_cfg_path,
            default_target_repo=_targeting_default_repo(self),
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return [_targeting_default_repo(self)]


def _derive_from_filename(self, filename: str) -> tuple[str | None, str | None]:
    if not self.cfg.autofill.derive_enabled:
        return None, None

    try:
        issue_re = re.compile(self.cfg.autofill.issue_regex)
    except re.error:
        issue_re = None
    try:
        msg_re = re.compile(self.cfg.autofill.commit_regex)
    except re.error:
        msg_re = None

    issue_id: str | None = None
    if issue_re is not None:
        m = issue_re.search(filename)
        if m and m.groups():
            issue_id = str(m.group(1))

    commit_msg: str | None = None
    if msg_re is not None:
        m2 = msg_re.match(filename)
        if m2 and m2.groups():
            commit_msg = str(m2.group(1))

    if commit_msg is None:
        dflt = str(self.cfg.autofill.commit_default_if_no_match or "")
        if dflt == "basename_no_ext":
            commit_msg = os.path.splitext(filename)[0]

    if commit_msg is not None:
        if self.cfg.autofill.commit_replace_underscores:
            commit_msg = commit_msg.replace("_", " ")
        if self.cfg.autofill.commit_replace_dashes:
            commit_msg = commit_msg.replace("-", " ")
        if self.cfg.autofill.commit_collapse_spaces:
            commit_msg = " ".join(commit_msg.split())
        if self.cfg.autofill.commit_trim:
            commit_msg = commit_msg.strip()
        if self.cfg.autofill.commit_ascii_only:
            commit_msg = _ascii_sanitize(commit_msg)
            if self.cfg.autofill.commit_collapse_spaces:
                commit_msg = " ".join(commit_msg.split())
            if self.cfg.autofill.commit_trim:
                commit_msg = commit_msg.strip()
        if commit_msg == "":
            commit_msg = None

    if issue_id is None:
        dflt_issue = str(self.cfg.autofill.issue_default_if_no_match or "")
        issue_id = dflt_issue if dflt_issue else None

    return issue_id, commit_msg


# ---------------- API ----------------


def api_config(self) -> tuple[int, bytes]:
    runner_cfg_path = (self.repo_root / self.cfg.runner.runner_config_toml).resolve()
    target_options = _target_options(self)
    success_rel = compute_success_archive_rel(
        self.repo_root, runner_cfg_path, self.cfg.paths.patches_root
    )

    data: dict[str, Any] = {
        "meta": {"version": self.cfg.meta.version},
        "server": {"host": self.cfg.server.host, "port": self.cfg.server.port},
        "runner": {
            "command": self.cfg.runner.command,
            "default_verbosity": self.cfg.runner.default_verbosity,
            "queue_enabled": self.cfg.runner.queue_enabled,
            "runner_config_toml": self.cfg.runner.runner_config_toml,
            "success_archive_rel": success_rel,
        },
        "paths": {
            "patches_root": self.cfg.paths.patches_root,
            "upload_dir": self.cfg.paths.upload_dir,
            "allow_crud": self.cfg.paths.allow_crud,
            "crud_allowlist": self.cfg.paths.crud_allowlist,
        },
        "upload": {
            "max_bytes": self.cfg.upload.max_bytes,
            "allowed_extensions": self.cfg.upload.allowed_extensions,
            "ascii_only_names": self.cfg.upload.ascii_only_names,
        },
        "issue": {
            "default_regex": self.cfg.issue.default_regex,
            "allocation_start": self.cfg.issue.allocation_start,
            "allocation_max": self.cfg.issue.allocation_max,
        },
        "indexing": {
            "log_filename_regex": self.cfg.indexing.log_filename_regex,
            "stats_windows_days": self.cfg.indexing.stats_windows_days,
        },
        "ui": {
            "base_font_px": self.cfg.ui.base_font_px,
            "drop_overlay_enabled": self.cfg.ui.drop_overlay_enabled,
            "clear_output_on_autofill": self.cfg.ui.clear_output_on_autofill,
            "show_autofill_clear_status": self.cfg.ui.show_autofill_clear_status,
            "idle_auto_select_last_job": self.cfg.ui.idle_auto_select_last_job,
        },
        "autofill": {
            "enabled": self.cfg.autofill.enabled,
            "poll_interval_seconds": self.cfg.autofill.poll_interval_seconds,
            "overwrite_policy": self.cfg.autofill.overwrite_policy,
            "fill_patch_path": self.cfg.autofill.fill_patch_path,
            "fill_issue_id": self.cfg.autofill.fill_issue_id,
            "fill_commit_message": self.cfg.autofill.fill_commit_message,
            "scan_dir": self.cfg.autofill.scan_dir,
            "scan_extensions": self.cfg.autofill.scan_extensions,
            "scan_ignore_filenames": self.cfg.autofill.scan_ignore_filenames,
            "scan_ignore_prefixes": self.cfg.autofill.scan_ignore_prefixes,
            "scan_zip_require_patch": self.cfg.autofill.scan_zip_require_patch,
            "choose_strategy": self.cfg.autofill.choose_strategy,
            "tiebreaker": self.cfg.autofill.tiebreaker,
            "derive_enabled": self.cfg.autofill.derive_enabled,
            "issue_regex": self.cfg.autofill.issue_regex,
            "commit_regex": self.cfg.autofill.commit_regex,
            "commit_replace_underscores": self.cfg.autofill.commit_replace_underscores,
            "commit_replace_dashes": self.cfg.autofill.commit_replace_dashes,
            "commit_collapse_spaces": self.cfg.autofill.commit_collapse_spaces,
            "commit_trim": self.cfg.autofill.commit_trim,
            "commit_ascii_only": self.cfg.autofill.commit_ascii_only,
            "issue_default_if_no_match": self.cfg.autofill.issue_default_if_no_match,
            "commit_default_if_no_match": self.cfg.autofill.commit_default_if_no_match,
        },
        "targeting": {
            "options": target_options,
            "default_target_repo": _targeting_default_repo(self),
            "zip_target_prefill_enabled": bool(
                getattr(getattr(self.cfg, "targeting", None), "zip_target_prefill_enabled", True)
            ),
        },
    }
    return _json_bytes(data)


def api_patches_latest(self, qs: dict[str, str] | None = None) -> tuple[int, bytes]:
    if not self.cfg.autofill.enabled:
        return _ok({"found": False, "disabled": True})
    if self.cfg.autofill.choose_strategy != "mtime_ns":
        return _err("Unsupported choose_strategy", status=400)
    if self.cfg.autofill.tiebreaker != "lex_name":
        return _err("Unsupported tiebreaker", status=400)

    qs = qs or {}
    since_token = str(qs.get("since_token", "") or "").strip()
    if not since_token:
        since_token = str(qs.get("since_sig", "") or "").strip()

    rel = self._autofill_scan_dir_rel()
    if rel is None:
        return _err("scan_dir must be under patches_root", status=400)

    try:
        d = self.jail.resolve_rel(rel)
    except Exception as e:
        return _err(str(e), status=400)
    if not d.exists() or not d.is_dir():
        payload_nf: dict[str, Any] = {
            "found": False,
            "status": [
                "autofill scan: scanned=0 ignored_name=0 ignored_prefix=0 "
                "ignored_ext=0 ignored_zip_no_patch=0 selected=none",
            ],
        }
        return _ok(payload_nf)

    exts = {str(x).lower() for x in self.cfg.autofill.scan_extensions}
    ignore_names = {str(x) for x in self.cfg.autofill.scan_ignore_filenames}
    ignore_pfx = [str(x) for x in self.cfg.autofill.scan_ignore_prefixes]

    best_name: str | None = None
    best_m = -1
    scanned = 0
    ignored_name = 0
    ignored_prefix = 0
    ignored_ext = 0
    ignored_zip_no_patch = 0
    for p in d.iterdir():
        if not p.is_file():
            continue
        scanned += 1
        name = p.name
        if name in ignore_names:
            ignored_name += 1
            continue
        if any(name.startswith(px) for px in ignore_pfx):
            ignored_prefix += 1
            continue
        if os.path.splitext(name)[1].lower() not in exts:
            ignored_ext += 1
            continue
        if os.path.splitext(name)[1].lower() == ".zip" and self.cfg.autofill.scan_zip_require_patch:
            ok, _reason = zip_contains_patch_file(p)
            if not ok:
                ignored_zip_no_patch += 1
                continue
        try:
            st = p.stat()
        except Exception:
            continue
        m_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
        if m_ns > best_m or (m_ns == best_m and (best_name is None or name < best_name)):
            best_m = m_ns
            best_name = name

    if not best_name:
        payload_nf2: dict[str, Any] = {
            "found": False,
            "status": [
                "autofill scan: "
                f"scanned={scanned} ignored_name={ignored_name} "
                f"ignored_prefix={ignored_prefix} ignored_ext={ignored_ext} "
                f"ignored_zip_no_patch={ignored_zip_no_patch} "
                "selected=none",
            ],
        }
        return _ok(payload_nf2)

    rel_dir = self.cfg.autofill.scan_dir.rstrip("/")
    stored_rel = str(Path(rel_dir) / best_name)
    issue_id, commit_msg = self._derive_from_filename(best_name)
    zip_commit_used = False
    zip_commit_err: str | None = None
    zip_issue_used = False
    zip_issue_err: str | None = None
    zip_target_repo: str | None = None
    zip_target_err: str | None = None
    if os.path.splitext(best_name)[1].lower() == ".zip" and self.cfg.autofill.zip_commit_enabled:
        zcfg = ZipCommitConfig(
            enabled=True,
            filename=self.cfg.autofill.zip_commit_filename,
            max_bytes=self.cfg.autofill.zip_commit_max_bytes,
            max_ratio=self.cfg.autofill.zip_commit_max_ratio,
        )
        zmsg, zerr = read_commit_message_from_zip_path(d / best_name, zcfg)
        if zmsg is not None:
            commit_msg = zmsg
            zip_commit_used = True
        else:
            zip_commit_err = zerr
    if os.path.splitext(best_name)[1].lower() == ".zip" and self.cfg.autofill.zip_issue_enabled:
        zicfg = ZipIssueConfig(
            enabled=True,
            filename=self.cfg.autofill.zip_issue_filename,
            max_bytes=self.cfg.autofill.zip_issue_max_bytes,
            max_ratio=self.cfg.autofill.zip_issue_max_ratio,
        )
        zid, zerr2 = read_issue_number_from_zip_path(d / best_name, zicfg)
        if zid is not None:
            issue_id = zid
            zip_issue_used = True
        else:
            zip_issue_err = zerr2
    if os.path.splitext(best_name)[1].lower() == ".zip":
        ztcfg = ZipTargetConfig(
            enabled=True,
            filename="target.txt",
            max_bytes=128,
            max_ratio=200,
        )
        zip_target_repo, zip_target_err = read_target_repo_from_zip_path(
            d / best_name,
            ztcfg,
        )

    payload: dict[str, Any] = {
        "found": True,
        "filename": best_name,
        "stored_rel_path": stored_rel,
        "mtime_ns": best_m,
        "token": f"{best_m}:{stored_rel}",
        "status": [
            "autofill scan: "
            f"scanned={scanned} ignored_name={ignored_name} "
            f"ignored_prefix={ignored_prefix} ignored_ext={ignored_ext} "
            f"ignored_zip_no_patch={ignored_zip_no_patch} "
            f"selected={best_name}",
        ],
    }

    if since_token and since_token == str(payload.get("token", "")):
        return _ok({"unchanged": True, "token": payload.get("token", "")})

    if self.cfg.autofill.derive_enabled:
        payload["derived_issue"] = issue_id
        payload["derived_commit_message"] = commit_msg
    payload["derived_target_repo"] = zip_target_repo
    if zip_commit_used:
        payload["status"].append(
            f"autofill: commit from zip {self.cfg.autofill.zip_commit_filename}"
        )
    elif zip_commit_err:
        payload["status"].append(f"autofill: zip commit ignored ({zip_commit_err})")
    if zip_issue_used:
        payload["status"].append(f"autofill: issue from zip {self.cfg.autofill.zip_issue_filename}")
    elif zip_issue_err:
        payload["status"].append(f"autofill: zip issue ignored ({zip_issue_err})")
    if zip_target_repo is not None:
        payload["status"].append("autofill: target from zip target.txt")
    elif zip_target_err:
        payload["status"].append(f"autofill: zip target ignored ({zip_target_err})")
    return _ok(payload)


def api_parse_command(self, body: dict[str, Any]) -> tuple[int, bytes]:
    raw = str(body.get("raw", ""))
    try:
        parsed = parse_runner_command(raw)
    except CommandParseError as e:
        return _err(str(e), status=400)

    return _ok(
        {
            "status": ["parse_command: ok"],
            "parsed": {
                "mode": parsed.mode,
                "issue_id": parsed.issue_id,
                "commit_message": parsed.commit_message,
                "patch_path": parsed.patch_path,
                "gate_argv": parsed.gate_argv,
            },
            "canonical": {
                "argv": parsed.canonical_argv,
            },
        }
    )


def api_runs(self, qs: dict[str, str]) -> tuple[int, bytes]:
    since_sig = str(qs.get("since_sig", "")).strip()
    issue_id = qs.get("issue_id")
    result = qs.get("result")

    canceled_source = active_canceled_runs_source(self)
    base_sig = runs_signature(self.patches_root, self.cfg.indexing.log_filename_regex)
    canceled_sig = canceled_runs_signature(canceled_source)
    sig = f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}:c={canceled_sig[0]}:{canceled_sig[1]}"

    # Conditional refresh applies only to the default (unfiltered) runs list.
    if since_sig and not issue_id and not result and since_sig == sig:
        return _ok({"unchanged": True, "sig": sig})

    runs = iter_runs(self.patches_root, self.cfg.indexing.log_filename_regex)
    runs.extend(_iter_canceled_runs(canceled_source))

    runner_cfg_path = (self.repo_root / self.cfg.runner.runner_config_toml).resolve()
    success_rel = compute_success_archive_rel(
        self.repo_root, runner_cfg_path, self.cfg.paths.patches_root
    )

    runs = [
        _decorate_run(r, patches_root=self.patches_root, success_zip_rel=success_rel) for r in runs
    ]

    limit = int(qs.get("limit", "100"))

    if issue_id:
        try:
            iid = int(issue_id)
        except ValueError:
            return _err("Invalid issue_id", status=400)
        runs = [r for r in runs if r.issue_id == iid]
    if result:
        if result not in ("success", "fail", "unknown", "canceled"):
            return _err("Invalid result filter", status=400)
        runs = [r for r in runs if r.result == result]

    runs.sort(key=lambda r: (r.mtime_utc, r.issue_id), reverse=True)
    runs = runs[: max(1, min(limit, 500))]
    return _ok({"runs": [run_to_list_item_json(r) for r in runs], "sig": sig})


def api_run_detail(self, issue_id: int) -> tuple[int, bytes]:
    canceled_source = active_canceled_runs_source(self)
    runs = iter_runs(self.patches_root, self.cfg.indexing.log_filename_regex)
    runs.extend(_iter_canceled_runs(canceled_source))

    runner_cfg_path = (self.repo_root / self.cfg.runner.runner_config_toml).resolve()
    success_rel = compute_success_archive_rel(
        self.repo_root, runner_cfg_path, self.cfg.paths.patches_root
    )

    runs = [
        _decorate_run(r, patches_root=self.patches_root, success_zip_rel=success_rel) for r in runs
    ]

    for r in runs:
        if int(r.issue_id) == int(issue_id):
            return _ok({"run": r.__dict__})
    return _err("Not found", status=404)


def api_runner_tail(self, qs: dict[str, str]) -> tuple[int, bytes]:
    lines = int(qs.get("lines", "200"))
    tail = read_tail(
        self.patches_root / "am_patch.log",
        lines,
        max_bytes=self.cfg.server.tail_max_bytes,
        cache_max_entries=self.cfg.server.tail_cache_max_entries,
    )
    return _ok({"path": str(Path(self.cfg.paths.patches_root) / "am_patch.log"), "tail": tail})


def diagnostics(self) -> dict[str, Any]:
    runs = iter_runs(self.patches_root, self.cfg.indexing.log_filename_regex)
    stats = compute_stats(runs, self.cfg.indexing.stats_windows_days)
    qstate = self.queue.state()
    lock_held = False
    try:
        from .job_ids import is_lock_held

        lock_held = is_lock_held(self.jail.lock_path())
    except Exception:
        lock_held = False

    usage = shutil.disk_usage(str(self.patches_root))
    return {
        "queue": {"queued": qstate.queued, "running": qstate.running},
        "lock": {
            "path": str(Path(self.cfg.paths.patches_root) / "am_patch.lock"),
            "held": lock_held,
        },
        "disk": {
            "total": int(usage.total),
            "used": int(usage.used),
            "free": int(usage.free),
        },
        "resources": proc_resources.snapshot(),
        "runs": {"count": len(runs)},
        "stats": {
            "all_time": stats.all_time.__dict__,
            "windows": [w.__dict__ for w in stats.windows],
        },
    }
