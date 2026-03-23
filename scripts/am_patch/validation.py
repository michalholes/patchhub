from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch.errors import RunnerError
from am_patch.gates_policy_wiring import run_policy_gates


@dataclass(frozen=True)
class GateSummary:
    ok: bool
    failing_stage: str | None = None
    failing_reason: str | None = None


def run_validation(
    *,
    logger: Any,
    repo_root: Path,
    cwd: Path,
    paths: Any,
    policy: Any,
    cli_mode: str,
    issue_id: int | None,
    decision_paths: list[str],
    progress: Any,
    gate_step_callback: Any = None,
) -> GateSummary:
    if not getattr(policy, "gate_monolith_extensions", None):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "gate_monolith_extensions must be non-empty (use gates_skip_monolith or "
            "gate_monolith_enabled instead)",
        )
    run_policy_gates(
        logger=logger,
        cwd=cwd,
        repo_root=repo_root,
        policy=policy,
        decision_paths=decision_paths,
        progress=progress,
        gate_step_callback=gate_step_callback,
        workspaces_dir=paths.workspaces_dir,
        cli_mode=cli_mode,
        issue_id=issue_id,
    )
    return GateSummary(ok=True)
