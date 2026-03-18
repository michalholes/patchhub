from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from typing import Any

# NOTE: This module contains helpers extracted from scripts/am_patch.py:main().
# Behavior must remain identical. These helpers intentionally rely on runtime-
# bound globals (status/logger/policy/etc) which are set by the caller.


status: Any = None
logger: Any = None
policy: Any = None
repo_root: Any = None
paths: Any = None
cli: Any = None
run_badguys: Any = None
RunnerError: Any = None


def _emit_core(*, severity: str, line: str, kind: str | None = None) -> None:
    # Keep screen/log semantics identical: all normal output goes through Logger.
    status.break_line()
    logger.emit(severity=severity, channel="CORE", message=line + "\n", kind=kind)


def _stage_do(stage: str) -> None:
    status.set_stage(stage)
    _emit_core(severity="INFO", line=f"DO: {stage}", kind="DO")


def _stage_ok(stage: str) -> None:
    _emit_core(severity="INFO", line=f"OK: {stage}", kind="OK")


def _stage_fail(stage: str) -> None:
    _emit_core(severity="ERROR", line=f"FAIL: {stage}", kind="FAIL")


def _gate_progress(token: str) -> None:
    kind, _, stage = token.partition(":")
    if not stage or kind not in ("DO", "OK", "FAIL"):
        return
    status.set_stage(stage)
    if kind == "DO":
        _emit_core(severity="INFO", line=f"DO: {stage}", kind="DO")
    elif kind == "OK":
        _emit_core(severity="INFO", line=f"OK: {stage}", kind="OK")
    else:
        _emit_core(severity="ERROR", line=f"FAIL: {stage}", kind="FAIL")


def _is_runner_path(rel: str) -> bool:
    p = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not p:
        return False
    return (
        p == "scripts/am_patch.py"
        or p.startswith("scripts/am_patch/")
        or p
        in (
            "scripts/am_patch.md",
            "scripts/am_patch_specification.md",
            "scripts/am_patch_instructions.md",
        )
    )


def _runner_touched(paths: list[str]) -> bool:
    return any(_is_runner_path(p) for p in paths)


def _maybe_run_badguys(
    *,
    cwd: Path,
    decision_paths: list[str],
) -> None:
    mode = str(getattr(policy, "gate_badguys_runner", "auto") or "auto").strip().lower()
    if mode not in ("auto", "on", "off"):
        mode = "auto"

    if mode == "off":
        logger.line("gate_badguys=SKIP (disabled_by_policy)")
        return

    if mode == "auto" and not _runner_touched(decision_paths):
        logger.line("gate_badguys=SKIP (runner_not_touched)")
        return

    # mode == "on" OR (auto and runner_touched)
    reason = "forced_on" if mode == "on" else "runner_touched"
    logger.line(f"gate_badguys=DO ({reason})")
    stage = "GATE_BADGUYS"
    _gate_progress(f"DO:{stage}")
    # When running badguys from the live repo root (repo_root), badguys will
    # spawn nested am_patch runs. Those nested runs must not fight with this
    # parent runner's lock. Also, in workspace mode, we must test the patched
    # runner (workspace repo) instead of the live tree.
    #
    # Strategy:
    # - If badguys are invoked in a workspace repo (cwd != repo_root), run them
    #   directly there (they will naturally test the patched runner).
    # - If badguys are invoked in the live repo root (cwd == repo_root), clone
    #   the live repo into an isolated workspace subdir and run badguys there.
    #   This tests the current live state while avoiding lock conflicts.
    # badguys command/cwd are controllable via cfg and CLI.
    raw_cmd = getattr(policy, "gate_badguys_command", None)
    command: list[str]
    if raw_cmd is None:
        command = ["badguys/badguys.py", "-q"]
    elif isinstance(raw_cmd, str):
        command = shlex.split(raw_cmd)
    else:
        command = [str(x) for x in raw_cmd]
    if not command:
        command = ["badguys/badguys.py", "-q"]

    cwd_mode = str(getattr(policy, "gate_badguys_cwd", "auto") or "auto").strip().lower()
    if cwd_mode not in ("auto", "workspace", "clone", "live"):
        cwd_mode = "auto"
    logger.line(f"gate_badguys_cwd={cwd_mode}")

    run_cwd = cwd
    isolated_repo: Path | None = None
    if cwd_mode == "clone" or (cwd_mode == "auto" and cwd.resolve() == repo_root.resolve()):
        tag = f"{cli.mode}_{cli.issue_id or 'noissue'}"
        isolated_repo = paths.workspaces_dir / "_badguys_gate" / tag
        # Deterministic: always recreate.
        if isolated_repo.exists():
            shutil.rmtree(isolated_repo)
        isolated_repo.parent.mkdir(parents=True, exist_ok=True)
        src_repo = repo_root if cwd.resolve() == repo_root.resolve() else cwd
        logger.line(f"gate_badguys_repo=CLONE {src_repo} -> {isolated_repo}")
        r = logger.run_logged(
            ["git", "clone", "--no-hardlinks", str(src_repo), str(isolated_repo)],
            cwd=paths.workspaces_dir,
        )
        if r.returncode != 0:
            raise RunnerError("GATES", "GATES", "badguys clone failed")
        run_cwd = isolated_repo
    elif cwd_mode == "live":
        run_cwd = repo_root
        logger.line(f"gate_badguys_repo=LIVE {repo_root}")
    else:
        logger.line(f"gate_badguys_repo=CWD {cwd}")

    ok = False
    try:
        ok = run_badguys(logger, cwd=run_cwd, repo_root=repo_root, command=command)
    finally:
        if isolated_repo is not None:
            if ok:
                shutil.rmtree(isolated_repo, ignore_errors=True)
            else:
                logger.line(f"gate_badguys_repo_kept={isolated_repo}")
    _gate_progress(f"OK:{stage}" if ok else f"FAIL:{stage}")
    if not ok:
        raise RunnerError("GATES", "GATES", "gate failed: badguys")


def _under_targets(rel: str) -> bool:
    for t in policy.ruff_targets:
        t = (t or "").strip().rstrip("/")
        if not t:
            continue
        if rel == t or rel.startswith(t + "/"):
            return True
    return False


def _parse_gate_list(msg: str) -> list[str]:
    if "gates failed:" in msg:
        tail = msg.split("gates failed:", 1)[1]
        parts = [p.strip() for p in tail.split(",")]
        return [p for p in parts if p]
    if "gate failed:" in msg:
        tail = msg.split("gate failed:", 1)[1].strip()
        first = tail.split()[0] if tail else ""
        return [first] if first else []
    return []


def _stage_rank(stage: str) -> int:
    order = [
        "PATCH_APPLY",
        "SCOPE",
        "PROMOTE",
        "PREFLIGHT",
        "SECURITY",
        "GATE_COMPILE",
        "GATE_RUFF",
        "GATE_PYTEST",
        "GATE_MYPY",
        "GATE_DOCS",
        "GATE_BADGUYS",
        "GATES",
        "INTERNAL",
    ]
    try:
        return order.index(stage)
    except ValueError:
        return 10_000
