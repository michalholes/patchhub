from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any


class _AppendBadguysOverride(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        key: str,
        const_value: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._key = key
        self._const_value = const_value
        super().__init__(option_strings, dest, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        overrides = getattr(namespace, "overrides", None)
        if overrides is None:
            overrides = []
            namespace.overrides = overrides
        if values is None or (
            not isinstance(values, str) and isinstance(values, Sequence) and len(values) == 0
        ):
            value = self._const_value if self._const_value is not None else "true"
        elif isinstance(values, str):
            value = values
        else:
            value = ",".join(str(item) for item in values)
        overrides.append(f"{self._key}={value}")


def add_badguys_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skip-badguys",
        dest="skip_badguys",
        nargs=0,
        action=_AppendBadguysOverride,
        key="gates_skip_badguys",
        const_value="true",
        default=None,
    )
    parser.add_argument(
        "--no-skip-badguys",
        dest="skip_badguys",
        nargs=0,
        action=_AppendBadguysOverride,
        key="gates_skip_badguys",
        const_value="false",
        default=None,
    )
    parser.add_argument(
        "--badguys-mode",
        dest="badguys_mode",
        choices=["auto", "always"],
        action=_AppendBadguysOverride,
        key="gate_badguys_mode",
        default=None,
    )
    parser.add_argument(
        "--badguys-trigger-prefixes",
        dest="badguys_trigger_prefixes",
        metavar="CSV",
        action=_AppendBadguysOverride,
        key="gate_badguys_trigger_prefixes",
        default=None,
    )
    parser.add_argument(
        "--badguys-trigger-files",
        dest="badguys_trigger_files",
        metavar="CSV",
        action=_AppendBadguysOverride,
        key="gate_badguys_trigger_files",
        default=None,
    )
    parser.add_argument(
        "--badguys-command",
        dest="badguys_command",
        metavar="CMD",
        action=_AppendBadguysOverride,
        key="gate_badguys_command",
        default=None,
    )
