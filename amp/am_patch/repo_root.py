from __future__ import annotations

import subprocess
from pathlib import Path

_LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC: str | None = None


def _normalize_stderr(stderr: str | bytes | None) -> str:
    if stderr is None:
        return ""
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace")
    return str(stderr)


def consume_resolve_repo_root_diagnostic() -> str | None:
    global _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC
    message = _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC
    _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC = None
    return message


def resolve_repo_root(*, timeout_s: int = 0) -> Path:
    global _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC
    _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC = None
    try:
        return Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                check=True,
                text=True,
                capture_output=True,
                timeout=(int(timeout_s) if int(timeout_s) > 0 else None),
            ).stdout.strip()
        )
    except Exception as exc:
        stderr_text = _normalize_stderr(getattr(exc, "stderr", None)).strip()
        detail_lines = [
            "WARNING: repo-root fallback to Path.cwd() after git rev-parse --show-toplevel failed",
            f"reason={type(exc).__name__}: {exc}",
        ]
        if stderr_text:
            detail_lines.extend(["[stderr]", stderr_text])
        detail_lines.append("using Path.cwd() fallback")
        _LAST_RESOLVE_REPO_ROOT_DIAGNOSTIC = "\n".join(detail_lines) + "\n"
        return Path.cwd()


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False
