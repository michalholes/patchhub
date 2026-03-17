from __future__ import annotations

from dataclasses import dataclass

STAGES = (
    "BOOTSTRAP",
    "PREFLIGHT",
    "PATCH",
    "SCOPE",
    "GATES",
    "PROMOTION",
    "CLEANUP",
)

CATEGORIES = (
    "GIT",
    "MANIFEST",
    "SCOPE",
    "NOOP",
    "GATES",
    "PROMOTION",
    "CONFIG",
    "INTERNAL",
    "SECURITY",
    "CANCELED",
)

CANCEL_EXIT_CODE = 130


@dataclass(frozen=True)
class RunnerError(Exception):
    stage: str
    category: str
    message: str

    def __str__(self) -> str:
        return f"{self.stage}:{self.category}: {self.message}"


def fingerprint(err: RunnerError) -> str:
    # Deterministic fingerprint string (no timestamps).
    return "\n".join(
        [
            "AM_PATCH_FAILURE_FINGERPRINT:",
            f"- stage: {err.stage}",
            f"- category: {err.category}",
            f"- message: {err.message}",
        ]
    )


class RunnerCancelledError(RunnerError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(stage, "CANCELED", message)
