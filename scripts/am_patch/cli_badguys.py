from __future__ import annotations

import argparse
import shlex
from typing import Any, TypedDict

from am_patch.config import Policy
from am_patch.errors import RunnerError
from am_patch.policy_gate_modes import _normalize_prefixes


class _BadguysCliKwargs(TypedDict):
    skip_badguys: bool | None
    badguys_mode: str | None
    badguys_trigger_prefixes: str | None
    badguys_trigger_files: str | None
    badguys_command: str | None


def add_badguys_cli_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--skip-badguys",
        dest="skip_badguys",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Skip the badguys gate.",
    )
    p.add_argument(
        "--badguys-mode",
        dest="badguys_mode",
        choices=["auto", "always"],
        default=None,
        help="Control badguys auto or always mode.",
    )
    p.add_argument(
        "--badguys-trigger-prefixes",
        dest="badguys_trigger_prefixes",
        default=None,
        help="CSV repo-relative prefixes that trigger badguys in auto mode.",
    )
    p.add_argument(
        "--badguys-trigger-files",
        dest="badguys_trigger_files",
        default=None,
        help="CSV repo-relative files that trigger badguys in auto mode.",
    )
    p.add_argument(
        "--badguys-command",
        dest="badguys_command",
        default=None,
        help="BADGUYS gate command (argv string; parsed like shell).",
    )


def apply_badguys_cli_namespace_to_dataclass_kwargs(
    ns: argparse.Namespace,
) -> _BadguysCliKwargs:
    return {
        "skip_badguys": getattr(ns, "skip_badguys", None),
        "badguys_mode": getattr(ns, "badguys_mode", None),
        "badguys_trigger_prefixes": getattr(ns, "badguys_trigger_prefixes", None),
        "badguys_trigger_files": getattr(ns, "badguys_trigger_files", None),
        "badguys_command": getattr(ns, "badguys_command", None),
    }


def apply_badguys_cli_namespace_to_return_kwargs(
    ns: argparse.Namespace,
) -> _BadguysCliKwargs:
    return apply_badguys_cli_namespace_to_dataclass_kwargs(ns)


def apply_badguys_cli_overrides(policy: Policy, cli: Any) -> None:
    if getattr(cli, "skip_badguys", None) is not None:
        policy.gates_skip_badguys = bool(cli.skip_badguys)
        policy._src["gates_skip_badguys"] = "cli"
    if getattr(cli, "badguys_mode", None) is not None:
        policy.gate_badguys_mode = str(cli.badguys_mode).strip()
        policy._src["gate_badguys_mode"] = "cli"
    if getattr(cli, "badguys_trigger_prefixes", None) is not None:
        policy.gate_badguys_trigger_prefixes = _normalize_prefixes(
            cli.badguys_trigger_prefixes,
            code="INVALID_GATE_BADGUYS_TRIGGER_PREFIXES",
            key="gate_badguys_trigger_prefixes",
        )
        policy._src["gate_badguys_trigger_prefixes"] = "cli"
    if getattr(cli, "badguys_trigger_files", None) is not None:
        policy.gate_badguys_trigger_files = _normalize_prefixes(
            cli.badguys_trigger_files,
            code="INVALID_GATE_BADGUYS_TRIGGER_FILES",
            key="gate_badguys_trigger_files",
        )
        policy._src["gate_badguys_trigger_files"] = "cli"
    if getattr(cli, "badguys_command", None) is not None:
        command = shlex.split(str(cli.badguys_command))
        if not command:
            raise RunnerError("CONFIG", "INVALID", "gate_badguys_command must be non-empty")
        policy.gate_badguys_command = command
        policy._src["gate_badguys_command"] = "cli"
