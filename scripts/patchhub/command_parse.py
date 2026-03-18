from __future__ import annotations

import shlex
from dataclasses import dataclass

from .gate_argv import GateArgvError, split_gate_argv, validate_gate_argv
from .models import JobMode


class CommandParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCommand:
    mode: JobMode
    issue_id: str
    commit_message: str
    patch_path: str
    gate_argv: list[str]
    canonical_argv: list[str]


def _validated_gate_argv(tokens: list[str]) -> list[str]:
    try:
        return validate_gate_argv(tokens)
    except GateArgvError as e:
        raise CommandParseError(str(e)) from e


def parse_runner_command(raw: str) -> ParsedCommand:
    raw = raw.strip()
    if not raw:
        raise CommandParseError("Empty command")

    try:
        argv = shlex.split(raw)
    except ValueError as e:
        raise CommandParseError(str(e)) from e

    if len(argv) < 3:
        raise CommandParseError("Command is too short")

    try:
        idx = argv.index("scripts/am_patch.py")
    except ValueError as e:
        raise CommandParseError("Missing scripts/am_patch.py") from e

    prefix = argv[: idx + 1]
    rest = argv[idx + 1 :]

    flag_f = "-f" in rest
    flag_w = "-w" in rest
    flag_l = "-l" in rest
    flag_count = int(flag_f) + int(flag_w) + int(flag_l)
    if flag_count > 1:
        raise CommandParseError("Conflicting finalize/rerun flags")

    if flag_f:
        pos = list(rest)
        pos.remove("-f")
        try:
            pos, gate_argv = split_gate_argv(pos)
        except GateArgvError as e:
            raise CommandParseError(str(e)) from e
        if len(pos) != 1:
            raise CommandParseError("finalize_live requires exactly one MESSAGE argument")
        message = pos[0]
        if not message:
            raise CommandParseError("MESSAGE is empty")
        return ParsedCommand(
            mode="finalize_live",
            issue_id="",
            commit_message=message,
            patch_path="",
            gate_argv=gate_argv,
            canonical_argv=build_canonical_command(
                prefix,
                "finalize_live",
                "",
                message,
                "",
                gate_argv,
            ),
        )

    if flag_w:
        pos = list(rest)
        pos.remove("-w")
        pos, gate_argv = split_gate_argv(pos)
        if len(pos) != 1:
            raise CommandParseError("finalize_workspace requires exactly one ISSUE_ID argument")
        issue_id = pos[0]
        if not issue_id.isdigit():
            raise CommandParseError("ISSUE_ID must be digits")
        return ParsedCommand(
            mode="finalize_workspace",
            issue_id=issue_id,
            commit_message="",
            patch_path="",
            gate_argv=gate_argv,
            canonical_argv=prefix + ["-w", issue_id] + gate_argv,
        )

    pos = list(rest)
    if flag_l:
        pos.remove("-l")
    try:
        pos, gate_argv = split_gate_argv(pos)
    except GateArgvError as e:
        raise CommandParseError(str(e)) from e

    if len(pos) not in (2, 3):
        raise CommandParseError('Expected: ISSUE_ID "commit message" PATCH')

    issue_id = pos[0]
    commit_message = pos[1]
    patch_path = pos[2] if len(pos) == 3 else ""
    if not issue_id.isdigit():
        raise CommandParseError("ISSUE_ID must be digits")
    if not commit_message:
        raise CommandParseError("Commit message is empty")
    if len(pos) == 3 and not patch_path:
        raise CommandParseError("PATCH is empty")

    mode: JobMode = "rerun_latest" if flag_l else "patch"
    canonical = build_canonical_command(
        prefix,
        mode,
        issue_id,
        commit_message,
        patch_path,
        gate_argv,
    )
    return ParsedCommand(
        mode=mode,
        issue_id=issue_id,
        commit_message=commit_message,
        patch_path=patch_path,
        gate_argv=gate_argv,
        canonical_argv=canonical,
    )


def build_canonical_command(
    runner_prefix: list[str],
    mode: JobMode,
    issue_id: str,
    commit_message: str,
    patch_path: str,
    gate_argv: list[str] | None = None,
) -> list[str]:
    gate_tail = _validated_gate_argv(list(gate_argv or []))
    if mode == "finalize_live":
        return runner_prefix + ["-f", commit_message] + gate_tail
    if mode == "finalize_workspace":
        return runner_prefix + ["-w", issue_id] + gate_tail
    if mode == "rerun_latest":
        argv = runner_prefix + [issue_id, commit_message]
        if patch_path:
            argv.append(patch_path)
        argv.append("-l")
        return argv + gate_tail
    if mode in ("patch", "repair"):
        return runner_prefix + [issue_id, commit_message, patch_path] + gate_tail
    raise CommandParseError(f"Unsupported mode: {mode}")
