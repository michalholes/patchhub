from __future__ import annotations

import sys
from pathlib import Path

from am_patch.config import Policy
from am_patch.errors import RunnerError
from am_patch.log import Logger


def run_post_success_audit(logger: Logger, repo_root: Path, policy: Policy) -> None:
    """Run audit/audit_report.py after a successful push (best effort, deterministic)."""
    logger.section("AUDIT")
    if not policy.post_success_audit:
        logger.line("audit_report=SKIP (post_success_audit=false)")
        return

    r = logger.run_logged(
        [sys.executable, "-u", "audit/audit_report.py"],
        cwd=repo_root,
        timeout_stage="AUDIT",
    )
    if r.returncode != 0:
        raise RunnerError("AUDIT", "AUDIT_REPORT_FAILED", "audit/audit_report.py failed")
