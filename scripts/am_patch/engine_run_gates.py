from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .config import Policy
from .gates_policy_wiring import run_policy_gates
from .log import Logger


def run_finalize_gates(
    *,
    logger: Logger,
    repo_root: Path,
    decision_paths: list[str],
    policy: Policy,
    progress: Callable[[str], None] | None,
) -> None:
    run_policy_gates(
        logger=logger,
        cwd=repo_root,
        repo_root=repo_root,
        policy=policy,
        decision_paths=decision_paths,
        progress=progress,
    )
