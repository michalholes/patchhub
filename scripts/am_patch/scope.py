from __future__ import annotations

from pathlib import Path

from .errors import RunnerError
from .log import Logger


def _is_under_prefix(p: str, prefix: str) -> bool:
    p = _normalize_path(p)
    prefix = _normalize_path(prefix)
    if not prefix:
        return False
    if p == prefix.rstrip("/"):
        return True
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    return p.startswith(prefix)


# Blessed outputs produced by gates (ruff/pytest/mypy) that should not
# disqualify a patch and should be promotable without using -a.
# Keep this list deterministic and explicit.
DEFAULT_BLESSED_GATE_OUTPUTS = ("audit/results/pytest_junit.xml",)


def is_blessed_gate_output(
    p: str, blessed_outputs: tuple[str, ...] | list[str] = DEFAULT_BLESSED_GATE_OUTPUTS
) -> bool:
    np = _normalize_path(p)
    return any(np == _normalize_path(item) for item in blessed_outputs)


def blessed_gate_outputs_in(
    paths: list[str],
    *,
    blessed_outputs: tuple[str, ...] | list[str] = DEFAULT_BLESSED_GATE_OUTPUTS,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        np = _normalize_path(p)
        if not np or np in seen:
            continue
        if is_blessed_gate_output(np, blessed_outputs=blessed_outputs):
            seen.add(np)
            out.append(np)
    return out


# Runner/workspace-generated workfiles that must not affect scope enforcement.
# These files may appear during patch execution or gates and must never require -a.
DEFAULT_RUNNER_WORKFILE_PREFIXES = (
    ".am_patch/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "__pycache__/",
)
DEFAULT_RUNNER_WORKFILE_SUFFIXES = (".pyc",)
DEFAULT_RUNNER_WORKFILE_CONTAINS = ("/__pycache__/",)


def is_runner_workfile(
    p: str,
    *,
    ignore_prefixes: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_PREFIXES,
    ignore_suffixes: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_SUFFIXES,
    ignore_contains: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_CONTAINS,
) -> bool:
    np = _normalize_path(p)
    if not np:
        return False
    for pre in ignore_prefixes:
        if np == pre.rstrip("/") or np.startswith(pre):
            return True
    if any(c in np for c in ignore_contains):
        return True
    return any(np.endswith(suf) for suf in ignore_suffixes)


def _normalize_path(p: str) -> str:
    p = p.strip()
    if p.endswith("/") and p != "/":
        p = p.rstrip("/")
    return p


ChangedPathEntry = tuple[str, str]


def _status_code(line: str) -> str:
    if line.startswith("??"):
        return "??"
    return line[:2]


def _parse_changed_path_entries(stdout: str) -> list[ChangedPathEntry]:
    entries: list[ChangedPathEntry] = []
    for raw in stdout.splitlines():
        line = raw.rstrip("\n")
        if not line or len(line) < 4:
            continue
        status = _status_code(line)
        payload = line[3:].strip()
        if " -> " in payload:
            old, new = payload.split(" -> ", 1)
            entries.append((status, _normalize_path(old)))
            entries.append((status, _normalize_path(new)))
        else:
            entries.append((status, _normalize_path(payload)))

    seen: set[ChangedPathEntry] = set()
    out: list[ChangedPathEntry] = []
    for status, path in entries:
        item = (status, path)
        if not path or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def changed_path_entries(logger: Logger, repo: Path) -> list[ChangedPathEntry]:
    r = logger.run_logged(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        timeout_stage="SCOPE",
    )
    if r.returncode != 0:
        raise RunnerError("SCOPE", "GIT", "git status failed in workspace")
    return _parse_changed_path_entries(r.stdout or "")


def changed_paths(logger: Logger, repo: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for _status, path in changed_path_entries(logger, repo):
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def delta_paths(before: list[str], after: list[str]) -> list[str]:
    b = set(_normalize_path(x) for x in before)
    out: list[str] = []
    for p in after:
        np = _normalize_path(p)
        if np not in b:
            out.append(np)
    # unique preserve order
    seen: set[str] = set()
    final: list[str] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        final.append(p)
    return final


def enforce_scope_delta(
    logger: Logger,
    *,
    files_current: list[str],
    before: list[str],
    after: list[str],
    no_op_fail: bool,
    allow_no_op: bool,
    allow_outside_files: bool = False,
    allowed_union: list[str] | set[str] | None = None,
    declared_untouched_fail: bool = True,
    allow_declared_untouched: bool = False,
    blessed_outputs: tuple[str, ...] | list[str] = DEFAULT_BLESSED_GATE_OUTPUTS,
    ignore_prefixes: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_PREFIXES,
    ignore_suffixes: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_SUFFIXES,
    ignore_contains: tuple[str, ...] | list[str] = DEFAULT_RUNNER_WORKFILE_CONTAINS,
) -> list[str]:
    declared = {str(_normalize_path(p)) for p in files_current}
    allowed = {str(_normalize_path(p)) for p in (allowed_union or [])}

    # Touched paths are the currently-changed paths after patch execution.
    # (Do NOT compute a delta vs. 'before': a dirty workspace would otherwise mask real edits.)
    # Ignore runner-generated workfiles/caches for scope enforcement.
    touched = [
        p
        for p in after
        if not is_runner_workfile(
            p,
            ignore_prefixes=ignore_prefixes,
            ignore_suffixes=ignore_suffixes,
            ignore_contains=ignore_contains,
        )
    ]

    if touched:
        outside = [
            p
            for p in touched
            if (
                p not in declared
                and p not in allowed
                and not is_blessed_gate_output(p, blessed_outputs=blessed_outputs)
            )
        ]
        if outside and not allow_outside_files:
            raise RunnerError("SCOPE", "SCOPE", "touched undeclared paths: " + ", ".join(outside))
    else:
        if no_op_fail and not allow_no_op:
            raise RunnerError("SCOPE", "NOOP", "no changes made")

    if declared_untouched_fail and not allow_declared_untouched:
        untouched = [p for p in sorted(declared) if p not in set(touched)]
        if untouched:
            raise RunnerError("SCOPE", "SCOPE", "declared but not touched: " + ", ".join(untouched))

    return touched
