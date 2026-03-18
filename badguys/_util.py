from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_cmd(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True)


def _format_completed_process(cp: subprocess.CompletedProcess[str]) -> str:
    args = cp.args if isinstance(cp.args, list) else [str(cp.args)]
    out = ["$ " + " ".join(str(a) for a in args)]
    if cp.stdout:
        out.append(cp.stdout.rstrip("\n"))
    if cp.stderr:
        out.append(cp.stderr.rstrip("\n"))
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class CmdStep:
    argv: list[str]
    cwd: Path | None = None
    expect_rc: int = 0


@dataclass(frozen=True)
class FuncStep:
    """A controlled side-effect step executed by the engine.

    Tests may need to prepare workspace artifacts between runner invocations.
    The engine executes this callable and logs start/end and any exception.
    """

    name: str
    fn: Callable[[], None]


@dataclass(frozen=True)
class ExpectPathExists:
    path: Path


Step = CmdStep | FuncStep | ExpectPathExists


@dataclass
class Plan:
    steps: list[Step]
    cleanup_paths: list[Path] = field(default_factory=list)


def write_git_add_file_patch(patch_path: Path, rel_path: str, text: str) -> None:
    """Write a minimal 'git apply' patch that adds a new file with given text."""
    if not text.endswith("\n"):
        text = text + "\n"
    lines = text.splitlines(True)
    body = "".join(["+" + ln for ln in lines])
    content = (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        f"new file mode 100644\n"
        f"index 0000000..1111111\n"
        f"--- /dev/null\n"
        f"+++ b/{rel_path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}"
    )
    write_text(patch_path, content)


def write_git_replace_line_patch(
    patch_path: Path,
    rel_path: str,
    context_line: str,
    old_line: str,
    new_line: str,
) -> None:
    """Replace a single line using a context line (for stable patching)."""
    if not context_line.endswith("\n"):
        context_line += "\n"
    if not old_line.endswith("\n"):
        old_line += "\n"
    if not new_line.endswith("\n"):
        new_line += "\n"
    content = (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{rel_path}\n"
        f"+++ b/{rel_path}\n"
        f"@@ -1,2 +1,2 @@\n"
        f" {context_line}"
        f"-{old_line}"
        f"+{new_line}"
    )
    write_text(patch_path, content)


def _lock_path(repo_root: Path) -> Path:
    return repo_root / "patches" / "badguys.lock"


def _parse_lock_started(lock_path: Path) -> int | None:
    try:
        txt = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    for line in txt.splitlines():
        if line.startswith("started="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def acquire_lock(
    repo_root: Path,
    *,
    path: Path | None = None,
    ttl_seconds: int = 3600,
    on_conflict: str = "fail",
) -> None:
    lock_path = path if path is not None else _lock_path(repo_root)
    lock_path = lock_path if lock_path.is_absolute() else (repo_root / lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as e:
        if on_conflict != "steal":
            raise SystemExit(f"FAIL: lock exists: {lock_path}") from e

        started = _parse_lock_started(lock_path)
        now = int(time.time())
        stale = started is not None and (now - started) > int(ttl_seconds)
        if not stale:
            raise SystemExit(f"FAIL: lock exists (not stale): {lock_path}") from e

        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()

        # retry once
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)

    try:
        content = f"pid={os.getpid()}\nstarted={int(time.time())}\n"
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def release_lock(repo_root: Path, *, path: Path | None = None) -> None:
    lock_path = path if path is not None else _lock_path(repo_root)
    lock_path = lock_path if lock_path.is_absolute() else (repo_root / lock_path)
    with contextlib.suppress(FileNotFoundError):
        lock_path.unlink()


def format_result_line(test_name: str, ok: bool) -> str:
    # Pytest-like status words.
    status = "PASSED" if ok else "FAILED"

    # Color scheme aligned with pytest defaults:
    # - PASSED: green
    # - FAILED: red
    if os.environ.get("NO_COLOR"):
        colored = status
    else:
        colored = f"\x1b[32m{status}\x1b[0m" if ok else f"\x1b[31m{status}\x1b[0m"

    return f"{test_name} ... {colored}\n"


def print_result(test_name: str, ok: bool) -> None:
    # Convenience wrapper used by some callers.
    sys.stdout.write(format_result_line(test_name, ok))
    sys.stdout.flush()


def fail_commit_limit(central_log: Path, commit_limit: int, commit_tests: Sequence[object]) -> None:
    names = []
    for t in commit_tests:
        name = getattr(t, "name", None)
        if isinstance(name, str):
            names.append(name)
        else:
            names.append(str(t))

    msg = f"FAIL: commit_limit exceeded: selected={len(names)} limit={commit_limit}"
    event = {
        "type": "badguys_fail_commit_limit",
        "selected": len(names),
        "limit": int(commit_limit),
        "tests": list(names),
        "msg": msg,
    }
    with central_log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")

    print(msg, file=sys.stderr)
    for n in names:
        print(f" - {n}", file=sys.stderr)
    print("Fix: increase --commit-limit OR use --exclude/--include.", file=sys.stderr)
    raise SystemExit(1)


# --- Additional helpers for new tests (Batch 1) ---


def assert_path_missing(path: Path) -> None:
    if path.exists():
        raise AssertionError(f"expected path to be missing: {path}")


def assert_file_contains(path: Path, needle: str) -> None:
    data = path.read_text(encoding="utf-8", errors="replace")
    if needle not in data:
        raise AssertionError(f"expected file to contain {needle!r}: {path}")


def assert_file_not_contains(path: Path, needle: str) -> None:
    data = path.read_text(encoding="utf-8", errors="replace")
    if needle in data:
        raise AssertionError(f"expected file to NOT contain {needle!r}: {path}")


def list_zip_entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        return sorted(zf.namelist())


def assert_zip_no_entries_matching(zip_path: Path, patterns: list[str]) -> None:
    entries = list_zip_entries(zip_path)
    bad: list[str] = []
    for e in entries:
        for pat in patterns:
            if fnmatch.fnmatch(e, pat):
                bad.append(e)
                break
    if bad:
        raise AssertionError(f"zip contains forbidden entries: {bad}")


def write_git_modify_file_patch(patch_path: Path, rel_path: str, old: str, new: str) -> None:
    """Write a minimal git-apply patch that replaces the entire file content."""
    if not old.endswith("\n"):
        old = old + "\n"
    if not new.endswith("\n"):
        new = new + "\n"
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)
    body = "".join(["-" + ln for ln in old_lines] + ["+" + ln for ln in new_lines])
    content = (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        f"index 2222222..3333333 100644\n"
        f"--- a/{rel_path}\n"
        f"+++ b/{rel_path}\n"
        f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@\n"
        f"{body}"
    )
    write_text(patch_path, content)


def write_git_noop_patch(patch_path: Path, rel_path: str) -> None:
    """A patch that declares a file but makes no effective changes (for NOOP enforcement)."""
    content = (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        f"index 1111111..1111111 100644\n"
        f"--- a/{rel_path}\n"
        f"+++ b/{rel_path}\n"
    )
    write_text(patch_path, content)


def write_patch_script(path: Path, *, files: list[str], body: str) -> None:
    """Write a runner python patch script with top-level FILES list."""
    files_list = "[" + ", ".join([repr(f) for f in files]) + "]"
    text = (
        "from __future__ import annotations\n\n"
        f"FILES = {files_list}\n\n"
        "from pathlib import Path\n\n"
        "REPO = Path(__file__).resolve().parents[1]\n\n"
        f"{body.strip()}\n"
    )
    write_text(path, text)


def write_zip(zip_path: Path, entries: list[tuple[str, bytes]]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
