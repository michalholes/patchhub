from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

from . import proc_resources
from .app_support import (
    active_canceled_runs_source,
    canceled_runs_signature,
    compute_success_archive_rel,
    decorate_run,
    iter_canceled_runs,
    read_tail,
)
from .app_support import (
    err as err_response,
)
from .app_support import (
    json_bytes as json_bytes_response,
)
from .app_support import (
    ok as ok_response,
)
from .command_parse import CommandParseError, parse_runner_command
from .indexing import compute_stats, iter_runs, runs_signature
from .models import AppStats, RunEntry, StatsWindow, run_to_list_item_json
from .patch_inventory import (
    autofill_ignore_reason,
    derive_filename_metadata,
    derive_patch_metadata,
)
from .targeting import (
    TargetCfgLike,
    resolve_targeting_runtime,
    validate_selected_target_repo,
)
from .zip_commit_message import zip_contains_patch_file

if TYPE_CHECKING:
    from .asgi.async_app_core import AsyncAppCore


def _autofill_scan_dir_rel(self: AsyncAppCore) -> str | None:
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


def derive_from_filename(
    self: AsyncAppCore,
    filename: str,
) -> tuple[str | None, str | None]:
    return derive_filename_metadata(self.cfg, filename)


autofill_scan_dir_rel = _autofill_scan_dir_rel
_derive_from_filename = derive_from_filename
_iter_canceled_runs = iter_canceled_runs
_decorate_run = decorate_run


def _run_sort_key(run: RunEntry) -> tuple[str, int]:
    return str(run.mtime_utc), int(run.issue_id)


def _stats_window_json(window: StatsWindow) -> dict[str, object]:
    return {
        "days": int(window.days),
        "total": int(window.total),
        "success": int(window.success),
        "fail": int(window.fail),
        "unknown": int(window.unknown),
    }


def _stats_json(stats: AppStats) -> dict[str, object]:
    return {
        "all_time": _stats_window_json(stats.all_time),
        "windows": [_stats_window_json(w) for w in stats.windows],
    }


def _run_detail_json(run: RunEntry) -> dict[str, object]:
    return {
        "issue_id": int(run.issue_id),
        "log_rel_path": str(run.log_rel_path),
        "result": str(run.result),
        "result_line": str(run.result_line) if run.result_line is not None else None,
        "mtime_utc": str(run.mtime_utc),
        "archived_patch_rel_path": (
            str(run.archived_patch_rel_path) if run.archived_patch_rel_path is not None else None
        ),
        "diff_bundle_rel_path": (
            str(run.diff_bundle_rel_path) if run.diff_bundle_rel_path is not None else None
        ),
        "success_zip_rel_path": (
            str(run.success_zip_rel_path) if run.success_zip_rel_path is not None else None
        ),
    }


# ---------------- API ----------------


def api_config(self: AsyncAppCore) -> tuple[int, bytes]:
    try:
        runtime = resolve_targeting_runtime(
            repo_root=self.repo_root,
            runner_config_toml=self.cfg.runner.runner_config_toml,
            target_cfg=cast(TargetCfgLike, self.cfg.targeting),
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        return err_response(str(e), status=400)
    success_rel = compute_success_archive_rel(
        self.repo_root, runtime.runner_config_toml, self.cfg.paths.patches_root
    )

    data: dict[str, object] = {
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
            "options": runtime.options,
            "default_target_repo": runtime.default_target_repo,
            "zip_target_prefill_enabled": bool(self.cfg.targeting.zip_target_prefill_enabled),
        },
    }
    return json_bytes_response(data)


def api_patches_latest(
    self: AsyncAppCore,
    qs: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    if not self.cfg.autofill.enabled:
        return ok_response({"found": False, "disabled": True})
    if self.cfg.autofill.choose_strategy != "mtime_ns":
        return err_response("Unsupported choose_strategy", status=400)
    if self.cfg.autofill.tiebreaker != "lex_name":
        return err_response("Unsupported tiebreaker", status=400)

    qs = qs or {}
    since_token = str(qs.get("since_token", "") or "").strip()
    if not since_token:
        since_token = str(qs.get("since_sig", "") or "").strip()

    rel = _autofill_scan_dir_rel(self)
    if rel is None:
        return err_response("scan_dir must be under patches_root", status=400)

    try:
        d = self.jail.resolve_rel(rel)
    except Exception as e:
        return err_response(str(e), status=400)
    if not d.exists() or not d.is_dir():
        payload_nf: dict[str, object] = {
            "found": False,
            "status": [
                "autofill scan: scanned=0 ignored_name=0 ignored_prefix=0 "
                "ignored_ext=0 ignored_zip_no_patch=0 selected=none",
            ],
        }
        return ok_response(payload_nf)

    exts = {str(x).lower() for x in self.cfg.autofill.scan_extensions}
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
        ignore_reason = autofill_ignore_reason(self.cfg, name)
        if ignore_reason == "name":
            ignored_name += 1
            continue
        if ignore_reason == "prefix":
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
        m_ns = int(st.st_mtime_ns)
        if m_ns > best_m or (m_ns == best_m and (best_name is None or name < best_name)):
            best_m = m_ns
            best_name = name

    if not best_name:
        payload_nf2: dict[str, object] = {
            "found": False,
            "status": [
                "autofill scan: "
                f"scanned={scanned} ignored_name={ignored_name} "
                f"ignored_prefix={ignored_prefix} ignored_ext={ignored_ext} "
                f"ignored_zip_no_patch={ignored_zip_no_patch} "
                "selected=none",
            ],
        }
        return ok_response(payload_nf2)

    rel_dir = self.cfg.autofill.scan_dir.rstrip("/")
    stored_rel = str(Path(rel_dir) / best_name)
    metadata = derive_patch_metadata(self, filename=best_name, path=d / best_name)

    status_lines = [
        "autofill scan: "
        f"scanned={scanned} ignored_name={ignored_name} "
        f"ignored_prefix={ignored_prefix} ignored_ext={ignored_ext} "
        f"ignored_zip_no_patch={ignored_zip_no_patch} "
        f"selected={best_name}",
    ]

    payload: dict[str, object] = {
        "found": True,
        "filename": best_name,
        "stored_rel_path": stored_rel,
        "mtime_ns": best_m,
        "token": f"{best_m}:{stored_rel}",
        "status": status_lines,
    }

    if since_token and since_token == str(payload.get("token", "")):
        return ok_response({"unchanged": True, "token": payload.get("token", "")})

    if self.cfg.autofill.derive_enabled:
        payload["derived_issue"] = metadata.derived_issue
        payload["derived_commit_message"] = metadata.derived_commit_message
    payload["derived_target_repo"] = metadata.derived_target_repo
    if metadata.zip_commit_used:
        status_lines.append(f"autofill: commit from zip {self.cfg.autofill.zip_commit_filename}")
    elif metadata.zip_commit_err:
        status_lines.append(f"autofill: zip commit ignored ({metadata.zip_commit_err})")
    if metadata.zip_issue_used:
        status_lines.append(f"autofill: issue from zip {self.cfg.autofill.zip_issue_filename}")
    elif metadata.zip_issue_err:
        status_lines.append(f"autofill: zip issue ignored ({metadata.zip_issue_err})")
    if metadata.derived_target_repo is not None:
        status_lines.append("autofill: target from zip target.txt")
    elif metadata.zip_target_err:
        status_lines.append(f"autofill: zip target ignored ({metadata.zip_target_err})")
    return ok_response(payload)


def api_parse_command(self: AsyncAppCore, body: dict[str, object]) -> tuple[int, bytes]:
    raw = str(body.get("raw", ""))
    try:
        parsed = parse_runner_command(raw)
    except CommandParseError as e:
        return err_response(str(e), status=400)

    if parsed.target_repo:
        try:
            runtime = resolve_targeting_runtime(
                repo_root=self.repo_root,
                runner_config_toml=self.cfg.runner.runner_config_toml,
                target_cfg=cast(TargetCfgLike, self.cfg.targeting),
            )
            validate_selected_target_repo(parsed.target_repo, runtime.options)
        except AttributeError:
            return err_response("targeting runtime is unavailable", status=400)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
            return err_response(str(e), status=400)

    return ok_response(
        {
            "status": ["parse_command: ok"],
            "parsed": {
                "mode": parsed.mode,
                "issue_id": parsed.issue_id,
                "commit_message": parsed.commit_message,
                "patch_path": parsed.patch_path,
                "gate_argv": parsed.gate_argv,
                "target_repo": parsed.target_repo,
            },
            "canonical": {
                "argv": parsed.canonical_argv,
            },
        }
    )


def api_runs(self: AsyncAppCore, qs: dict[str, str]) -> tuple[int, bytes]:
    since_sig = str(qs.get("since_sig", "")).strip()
    issue_id = qs.get("issue_id")
    result = qs.get("result")

    canceled_source = active_canceled_runs_source(self)
    base_sig = runs_signature(self.patches_root, self.cfg.indexing.log_filename_regex)
    canceled_sig = canceled_runs_signature(canceled_source)
    sig = f"runs:r={base_sig[0]}:{base_sig[1]}:{base_sig[2]}:c={canceled_sig[0]}:{canceled_sig[1]}"

    # Conditional refresh applies only to the default (unfiltered) runs list.
    if since_sig and not issue_id and not result and since_sig == sig:
        return ok_response({"unchanged": True, "sig": sig})

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
            return err_response("Invalid issue_id", status=400)
        runs = [r for r in runs if r.issue_id == iid]
    if result:
        if result not in ("success", "fail", "unknown", "canceled"):
            return err_response("Invalid result filter", status=400)
        runs = [r for r in runs if r.result == result]

    runs.sort(key=_run_sort_key, reverse=True)
    runs = runs[: max(1, min(limit, 500))]
    return ok_response({"runs": [run_to_list_item_json(r) for r in runs], "sig": sig})


def api_run_detail(self: AsyncAppCore, issue_id: int) -> tuple[int, bytes]:
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
            return ok_response({"run": _run_detail_json(r)})
    return err_response("Not found", status=404)


def api_runner_tail(self: AsyncAppCore, qs: dict[str, str]) -> tuple[int, bytes]:
    lines = int(qs.get("lines", "200"))
    tail = read_tail(
        self.patches_root / "am_patch.log",
        lines,
        max_bytes=self.cfg.server.tail_max_bytes,
        cache_max_entries=self.cfg.server.tail_cache_max_entries,
    )
    return ok_response(
        {
            "path": str(Path(self.cfg.paths.patches_root) / "am_patch.log"),
            "tail": tail,
        }
    )


def diagnostics(self: AsyncAppCore) -> dict[str, object]:
    runs = iter_runs(self.patches_root, self.cfg.indexing.log_filename_regex)
    stats = compute_stats(runs, self.cfg.indexing.stats_windows_days)
    queued = 0
    running = 0
    lock_held = False
    try:
        from .job_ids import is_lock_held

        lock_held = is_lock_held(self.jail.lock_path())
    except Exception:
        lock_held = False

    usage = shutil.disk_usage(str(self.patches_root))
    return {
        "queue": {"queued": queued, "running": running},
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
        "stats": _stats_json(stats),
    }
