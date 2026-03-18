from __future__ import annotations

import shlex
from dataclasses import dataclass

from .gate_argv import GateArgvError, validate_gate_argv
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
    target_repo: str


@dataclass(frozen=True)
class _TailOptions:
    target_repo: str
    gate_argv: list[str]


def _validated_gate_argv(tokens: list[str]) -> list[str]:
    try:
        return validate_gate_argv(tokens)
    except GateArgvError as e:
        raise CommandParseError(str(e)) from e


def _parse_tail_options(tokens: list[str]) -> _TailOptions:
    gate_tokens: list[str] = []
    target_repo = ""
    idx = 0
    while idx < len(tokens):
        token = str(tokens[idx] or "")
        if token == "--target-repo-name":
            if idx + 1 >= len(tokens):
                raise CommandParseError("--target-repo-name requires VALUE")
            if target_repo:
                raise CommandParseError("--target-repo-name may appear only once")
            target_repo = str(tokens[idx + 1] or "")
            idx += 2
            continue
        gate_tokens.append(token)
        idx += 1
    return _TailOptions(
        target_repo=target_repo,
        gate_argv=_validated_gate_argv(gate_tokens),
    )


def parse_runner_argv(argv: list[str]) -> ParsedCommand:
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
        if not pos:
            raise CommandParseError("finalize_live requires exactly one MESSAGE argument")
        message = str(pos[0] or "")
        if not message:
            raise CommandParseError("MESSAGE is empty")
        tail = _parse_tail_options(pos[1:])
        if len(pos[:1]) != 1:
            raise CommandParseError("finalize_live requires exactly one MESSAGE argument")
        return ParsedCommand(
            mode="finalize_live",
            issue_id="",
            commit_message=message,
            patch_path="",
            gate_argv=tail.gate_argv,
            canonical_argv=build_canonical_command(
                prefix,
                "finalize_live",
                "",
                message,
                "",
                tail.gate_argv,
                target_repo=tail.target_repo,
            ),
            target_repo=tail.target_repo,
        )

    if flag_w:
        pos = list(rest)
        pos.remove("-w")
        if not pos:
            raise CommandParseError("finalize_workspace requires exactly one ISSUE_ID argument")
        issue_id = str(pos[0] or "")
        if not issue_id.isdigit():
            raise CommandParseError("ISSUE_ID must be digits")
        tail = _parse_tail_options(pos[1:])
        return ParsedCommand(
            mode="finalize_workspace",
            issue_id=issue_id,
            commit_message="",
            patch_path="",
            gate_argv=tail.gate_argv,
            canonical_argv=build_canonical_command(
                prefix,
                "finalize_workspace",
                issue_id,
                "",
                "",
                tail.gate_argv,
                target_repo=tail.target_repo,
            ),
            target_repo=tail.target_repo,
        )

    pos = list(rest)
    if flag_l:
        pos.remove("-l")
    if len(pos) < 2:
        raise CommandParseError('Expected: ISSUE_ID "commit message" PATCH')

    issue_id = str(pos[0] or "")
    commit_message = str(pos[1] or "")
    if not issue_id.isdigit():
        raise CommandParseError("ISSUE_ID must be digits")
    if not commit_message:
        raise CommandParseError("Commit message is empty")

    patch_path = ""
    tail_tokens = pos[2:]
    if tail_tokens and not str(tail_tokens[0] or "").startswith("-"):
        patch_path = str(tail_tokens[0] or "")
        tail_tokens = tail_tokens[1:]
    if flag_l and not patch_path:
        patch_path = ""
    elif not flag_l and not patch_path:
        raise CommandParseError('Expected: ISSUE_ID "commit message" PATCH')
    tail = _parse_tail_options(tail_tokens)

    mode: JobMode = "rerun_latest" if flag_l else "patch"
    canonical = build_canonical_command(
        prefix,
        mode,
        issue_id,
        commit_message,
        patch_path,
        tail.gate_argv,
        target_repo=tail.target_repo,
    )
    return ParsedCommand(
        mode=mode,
        issue_id=issue_id,
        commit_message=commit_message,
        patch_path=patch_path,
        gate_argv=tail.gate_argv,
        canonical_argv=canonical,
        target_repo=tail.target_repo,
    )


def parse_runner_command(raw: str) -> ParsedCommand:
    raw = raw.strip()
    if not raw:
        raise CommandParseError("Empty command")

    try:
        argv = shlex.split(raw)
    except ValueError as e:
        raise CommandParseError(str(e)) from e
    return parse_runner_argv(argv)


def build_canonical_command(
    runner_prefix: list[str],
    mode: JobMode,
    issue_id: str,
    commit_message: str,
    patch_path: str,
    gate_argv: list[str] | None = None,
    target_repo: str = "",
) -> list[str]:
    gate_tail = _validated_gate_argv(list(gate_argv or []))
    target_tail = []
    if target_repo:
        target_tail = ["--target-repo-name", target_repo]
    if mode == "finalize_live":
        return runner_prefix + ["-f", commit_message] + target_tail + gate_tail
    if mode == "finalize_workspace":
        return runner_prefix + ["-w", issue_id] + target_tail + gate_tail
    if mode == "rerun_latest":
        argv = runner_prefix + [issue_id, commit_message]
        if patch_path:
            argv.append(patch_path)
        argv.append("-l")
        return argv + target_tail + gate_tail
    if mode in ("patch", "repair"):
        return runner_prefix + [issue_id, commit_message, patch_path] + target_tail + gate_tail
    raise CommandParseError(f"Unsupported mode: {mode}")
