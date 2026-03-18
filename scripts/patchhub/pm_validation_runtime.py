from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from .app_support import compute_success_archive_rel
from .zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
)
from .zip_patch_subset import resolve_patch_zip_path

_STATUS_PASS = "pass"
_STATUS_FAIL = "fail"
_STATUS_ERROR = "error"
_STATUS_MISSING_CONTEXT = "missing_context"


def _validator_script_path(repo_root: Path) -> Path:
    repo_candidate = (repo_root / "scripts" / "pm_validator.py").resolve()
    if repo_candidate.exists():
        return repo_candidate
    return (Path(__file__).resolve().parents[1] / "pm_validator.py").resolve()


def _zip_commit_cfg(cfg: Any) -> ZipCommitConfig:
    autofill = getattr(cfg, "autofill", object())
    return ZipCommitConfig(
        enabled=bool(getattr(autofill, "zip_commit_enabled", True)),
        filename=str(getattr(autofill, "zip_commit_filename", "COMMIT_MESSAGE.txt")),
        max_bytes=int(getattr(autofill, "zip_commit_max_bytes", 4096)),
        max_ratio=int(getattr(autofill, "zip_commit_max_ratio", 200)),
    )


def _zip_issue_cfg(cfg: Any) -> ZipIssueConfig:
    autofill = getattr(cfg, "autofill", object())
    return ZipIssueConfig(
        enabled=bool(getattr(autofill, "zip_issue_enabled", True)),
        filename=str(getattr(autofill, "zip_issue_filename", "ISSUE_NUMBER.txt")),
        max_bytes=int(getattr(autofill, "zip_issue_max_bytes", 128)),
        max_ratio=int(getattr(autofill, "zip_issue_max_ratio", 200)),
    )


def _derive_validation_inputs(self: Any, zpath: Path) -> tuple[str, str]:
    issue_id, _issue_err = read_issue_number_from_zip_path(zpath, _zip_issue_cfg(self.cfg))
    commit_message, _commit_err = read_commit_message_from_zip_path(
        zpath,
        _zip_commit_cfg(self.cfg),
    )
    if hasattr(self, "_derive_from_filename"):
        derived_issue, derived_commit = self._derive_from_filename(zpath.name)
    else:
        derived_issue, derived_commit = None, None
    return str(issue_id or derived_issue or ""), str(commit_message or derived_commit or "")


def _latest_file_by_pattern(root: Path, pattern: str) -> Path | None:
    best: Path | None = None
    best_key = (-1, "")
    for candidate in root.glob(pattern):
        if not candidate.is_file():
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        key = (int(getattr(stat, "st_mtime_ns", 0)), candidate.name)
        if key > best_key:
            best = candidate
            best_key = key
    return best


def _runner_config_path(repo_root: Path, cfg: Any) -> Path:
    rel = str(getattr(getattr(cfg, "runner", object()), "runner_config_toml", "")).strip()
    return (repo_root / rel).resolve()


def _latest_success_archive(repo_root: Path, patches_root: Path, cfg: Any) -> Path | None:
    runner_cfg_path = _runner_config_path(repo_root, cfg)
    if not runner_cfg_path.exists():
        return None
    raw = tomllib.loads(runner_cfg_path.read_text(encoding="utf-8"))
    paths_cfg = raw.get("paths", {})
    cleanup_glob = str(paths_cfg.get("success_archive_cleanup_glob_template", "")).strip()
    archive_dir = str(paths_cfg.get("success_archive_dir", "patch_dir")).strip() or "patch_dir"
    dest_root = patches_root if archive_dir == "patch_dir" else (patches_root / "successful")
    if cleanup_glob:
        latest = _latest_file_by_pattern(dest_root, cleanup_glob)
        if latest is not None:
            return latest.resolve()
    try:
        rel = compute_success_archive_rel(repo_root, runner_cfg_path, str(cfg.paths.patches_root))
    except Exception:
        return None
    candidate = (patches_root / rel).resolve()
    return candidate if candidate.exists() and candidate.is_file() else None


def _latest_repair_overlay(patches_root: Path, issue_id: str) -> Path | None:
    clean_issue = str(issue_id or "").strip()
    if not clean_issue.isdigit():
        return None
    return _latest_file_by_pattern(patches_root, f"patched_issue{clean_issue}_*.zip")


def _manual_workspace_snapshot(repo_root: Path, dest_zip: Path) -> Path:
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(repo_root.rglob("*")):
            if not fp.is_file():
                continue
            rel = fp.relative_to(repo_root)
            if ".git" in rel.parts:
                continue
            zf.write(fp, arcname=str(rel).replace("\\", "/"))
    return dest_zip


def _live_workspace_snapshot(repo_root: Path, dest_zip: Path) -> Path:
    git_dir = repo_root / ".git"
    if git_dir.exists():
        proc = subprocess.run(
            ["git", "archive", "--format=zip", "-o", str(dest_zip), "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and dest_zip.exists():
            return dest_zip
    return _manual_workspace_snapshot(repo_root, dest_zip)


def _raw_output(stdout: str, stderr: str) -> str:
    out = str(stdout or "")
    err = str(stderr or "")
    if out and err:
        return out.rstrip("\n") + "\n\n[stderr]\n" + err
    if err:
        return "[stderr]\n" + err
    return out


def _parse_status(returncode: int, raw_output: str) -> str:
    if returncode == 0 and "RESULT: PASS" in raw_output:
        return _STATUS_PASS
    if any(
        token in raw_output
        for token in (
            "workspace_snapshot_required_for_initial_mode",
            "repair_overlay_not_found",
            "supplemental_requires_workspace_snapshot",
        )
    ):
        return _STATUS_MISSING_CONTEXT
    return _STATUS_FAIL


def _run_validator(
    *,
    repo_root: Path,
    issue_id: str,
    commit_message: str,
    patch_zip: Path,
    workspace_snapshot: Path | None,
    repair_overlay: Path | None,
    supplemental_files: list[str],
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_validator_script_path(repo_root)),
        str(issue_id),
        str(commit_message),
        str(patch_zip),
    ]
    if workspace_snapshot is not None:
        cmd.extend(["--workspace-snapshot", str(workspace_snapshot)])
    if repair_overlay is not None:
        cmd.extend(["--repair-overlay", str(repair_overlay)])
    for item in supplemental_files:
        cmd.extend(["--supplemental-file", str(item)])
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_repair_requires_supplemental(raw_output: str) -> list[str]:
    marker = "repair_requires_supplemental_file:"
    for line in str(raw_output or "").splitlines():
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            parsed = ast.literal_eval(payload)
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        out: list[str] = []
        for item in parsed:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    return []


def _authority_label(path: Path, *, patches_root: Path) -> str:
    try:
        return str(path.relative_to(patches_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def build_patch_zip_pm_validation(self: Any, patch_path: str) -> dict[str, Any]:
    patch_rel, patch_zip = resolve_patch_zip_path(
        jail=self.jail,
        patches_root_rel=self.cfg.paths.patches_root,
        patch_path=str(patch_path or ""),
    )
    issue_id, commit_message = _derive_validation_inputs(self, patch_zip)
    overlay_path = _latest_repair_overlay(self.patches_root, issue_id)
    effective_mode = "repair-overlay-only" if overlay_path is not None else "initial"
    authority_sources: list[str] = []
    supplemental_files: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        workspace_snapshot: Path | None = None
        if overlay_path is None:
            success_archive = _latest_success_archive(self.repo_root, self.patches_root, self.cfg)
            if success_archive is not None:
                workspace_snapshot = success_archive
                authority_sources.append(
                    _authority_label(success_archive, patches_root=self.patches_root)
                )
            else:
                try:
                    workspace_snapshot = _live_workspace_snapshot(
                        self.repo_root,
                        temp_root / "live_workspace_snapshot.zip",
                    )
                except Exception as exc:
                    return {
                        "status": _STATUS_MISSING_CONTEXT,
                        "effective_mode": "initial",
                        "issue_id": issue_id,
                        "commit_message": commit_message,
                        "patch_path": patch_rel,
                        "authority_sources": [],
                        "supplemental_files": [],
                        "raw_output": (
                            "PHB could not obtain a workspace snapshot fallback.\n" + str(exc)
                        ),
                    }
                authority_sources.append("live_workspace_snapshot")
        else:
            authority_sources.append(_authority_label(overlay_path, patches_root=self.patches_root))

        proc = _run_validator(
            repo_root=self.repo_root,
            issue_id=issue_id,
            commit_message=commit_message,
            patch_zip=patch_zip,
            workspace_snapshot=workspace_snapshot,
            repair_overlay=overlay_path,
            supplemental_files=[],
        )
        raw = _raw_output(proc.stdout, proc.stderr)

        if overlay_path is not None:
            supplemental_files = _parse_repair_requires_supplemental(raw)
            if supplemental_files:
                success_archive = _latest_success_archive(
                    self.repo_root,
                    self.patches_root,
                    self.cfg,
                )
                if success_archive is not None:
                    workspace_snapshot = success_archive
                    authority_label = _authority_label(
                        success_archive,
                        patches_root=self.patches_root,
                    )
                else:
                    try:
                        workspace_snapshot = _live_workspace_snapshot(
                            self.repo_root,
                            temp_root / "repair_workspace_snapshot.zip",
                        )
                    except Exception as exc:
                        return {
                            "status": _STATUS_MISSING_CONTEXT,
                            "effective_mode": "repair-overlay-only",
                            "issue_id": issue_id,
                            "commit_message": commit_message,
                            "patch_path": patch_rel,
                            "authority_sources": authority_sources,
                            "supplemental_files": supplemental_files,
                            "raw_output": raw.rstrip("\n")
                            + "\n\n[repair supplemental snapshot error]\n"
                            + str(exc),
                        }
                    authority_label = "live_workspace_snapshot"
                if authority_label not in authority_sources:
                    authority_sources.append(authority_label)
                proc = _run_validator(
                    repo_root=self.repo_root,
                    issue_id=issue_id,
                    commit_message=commit_message,
                    patch_zip=patch_zip,
                    workspace_snapshot=workspace_snapshot,
                    repair_overlay=overlay_path,
                    supplemental_files=supplemental_files,
                )
                rerun_raw = _raw_output(proc.stdout, proc.stderr)
                effective_mode = "repair-supplemental"
                raw = (
                    "[overlay-only]\n"
                    + raw.rstrip("\n")
                    + "\n\n[repair-supplemental]\n"
                    + rerun_raw
                )

        return {
            "status": _parse_status(proc.returncode, raw),
            "effective_mode": effective_mode,
            "issue_id": issue_id,
            "commit_message": commit_message,
            "patch_path": patch_rel,
            "authority_sources": authority_sources,
            "supplemental_files": supplemental_files,
            "raw_output": raw,
        }


def pm_validation_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)
