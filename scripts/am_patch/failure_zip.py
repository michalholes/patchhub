from __future__ import annotations

import hashlib
from pathlib import Path

from am_patch.config import Policy


def effective_issue_id(*, issue_id: int | None, pseudo_issue_id: str | None) -> str:
    """Return a stable issue identifier for artifact naming.

    - For normal runs, use the numeric issue id.
    - For finalize/no-issue runs, use the provided pseudo issue id.
    """

    if issue_id is not None:
        return str(issue_id)
    if pseudo_issue_id:
        return str(pseudo_issue_id)
    return "NONE"


def _extract_ts_from_log_name(*, policy: Policy, log_path: Path, issue: str) -> str:
    """Extract {ts} from the log filename using configured templates.

    This avoids introducing new time dependence for failure zip naming.
    """

    name = log_path.name

    if "{issue}" in policy.log_template_issue and "{ts}" in policy.log_template_issue:
        try:
            t = str(policy.log_template_issue)
            prefix, suffix = t.split("{ts}")
            prefix = prefix.format(issue=issue)
            if name.startswith(prefix) and name.endswith(suffix):
                return name[len(prefix) : len(name) - len(suffix)]
        except Exception:
            pass

    if "{ts}" in policy.log_template_finalize:
        try:
            t = str(policy.log_template_finalize)
            prefix, suffix = t.split("{ts}")
            if name.startswith(prefix) and name.endswith(suffix):
                return name[len(prefix) : len(name) - len(suffix)]
        except Exception:
            pass

    return log_path.stem


def _log_nonce(*, log_path: Path) -> str:
    """Return a short deterministic nonce derived from log contents."""

    h = hashlib.sha256()
    try:
        with log_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        h.update(str(log_path).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:12]


def _failure_zip_sort_key(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, path.name


def render_name(*, policy: Policy, issue: str, log_path: Path, attempt: int | None) -> str:
    """Render the failure zip filename from policy template."""

    template = policy.failure_zip_template or ""
    if not template.strip():
        return str(policy.failure_zip_name)

    ts = _extract_ts_from_log_name(policy=policy, log_path=log_path, issue=issue)
    nonce = _log_nonce(log_path=log_path)
    attempt_i = int(attempt) if attempt is not None else 1
    rendered = template.format(
        issue=issue,
        ts=ts,
        nonce=nonce,
        log=log_path.stem,
        attempt=attempt_i,
    )

    name = Path(rendered).name
    if not name.lower().endswith(".zip"):
        name = f"{name}.zip"
    return name


def cleanup_for_issue(*, patch_dir: Path, policy: Policy, issue: str) -> None:
    """Apply per-issue retention for failure zips (best-effort)."""

    if not policy.failure_zip_enabled:
        return

    keep = int(policy.failure_zip_keep_per_issue)
    if keep < 0:
        keep = 0

    glob_tmpl = policy.failure_zip_cleanup_glob_template
    if not glob_tmpl:
        glob_tmpl = "patched_issue{issue}_*.zip"
    pattern = glob_tmpl.format(issue=issue)

    matches = sorted(
        (p for p in patch_dir.glob(pattern) if p.is_file()),
        key=_failure_zip_sort_key,
        reverse=True,
    )
    for p in matches[keep:]:
        try:
            p.unlink()
        except Exception:
            continue


def cleanup_on_success_commit(*, patch_dir: Path, policy: Policy, issue: str) -> None:
    """Remove failure zips for issue after a successful commit (best-effort)."""

    if not policy.failure_zip_enabled:
        return

    if not policy.failure_zip_delete_on_success_commit:
        return

    glob_tmpl = policy.failure_zip_cleanup_glob_template
    if not glob_tmpl:
        glob_tmpl = "patched_issue{issue}_*.zip"
    pattern = glob_tmpl.format(issue=issue)

    for p in patch_dir.glob(pattern):
        if not p.is_file():
            continue
        try:
            p.unlink()
        except Exception:
            continue
