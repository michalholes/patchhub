from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

_last_resolve_repo_root_diagnostic: str | None = None


@runtime_checkable
class _HasStderr(Protocol):
    stderr: object


def _normalize_stderr(stderr: str | bytes | None) -> str:
    if stderr is None:
        return ""
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace")
    return str(stderr)


def consume_resolve_repo_root_diagnostic() -> str | None:
    global _last_resolve_repo_root_diagnostic
    message = _last_resolve_repo_root_diagnostic
    _last_resolve_repo_root_diagnostic = None
    return message


def _stderr_from_exception(exc: BaseException) -> str | bytes | None:
    if not isinstance(exc, _HasStderr):
        return None
    raw = exc.stderr
    if raw is None or isinstance(raw, (str, bytes)):
        return raw
    return str(raw)


def resolve_repo_root(*, timeout_s: int = 0) -> Path:
    global _last_resolve_repo_root_diagnostic
    _last_resolve_repo_root_diagnostic = None
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
        stderr_text = _normalize_stderr(_stderr_from_exception(exc)).strip()
        detail_lines = [
            "WARNING: repo-root fallback to Path.cwd() after git rev-parse --show-toplevel failed",
            f"reason={type(exc).__name__}: {exc}",
        ]
        if stderr_text:
            detail_lines.extend(["[stderr]", stderr_text])
        detail_lines.append("using Path.cwd() fallback")
        _last_resolve_repo_root_diagnostic = "\n".join(detail_lines) + "\n"
        return Path.cwd()


def resolve_repo_root_strict_from_cwd(*, timeout_s: int = 0) -> Path:
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
        detail = (
            "finalize-live-from-cwd selected but git rev-parse --show-toplevel failed "
            "from current working directory"
        )
        stderr_text = _normalize_stderr(_stderr_from_exception(exc)).strip()
        detail = f"{detail}: {type(exc).__name__}: {exc}"
        if stderr_text:
            detail = f"{detail}; stderr={stderr_text}"
        raise RuntimeError(detail) from exc


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False
