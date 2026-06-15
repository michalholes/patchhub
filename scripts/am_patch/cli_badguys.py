from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import cast


class _AppendBadguysOverride(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        key: str,
        const_value: str | None = None,
        nargs: int | str | None = None,
        const: object | None = None,
        default: object | None = None,
        type: Callable[[str], object] | None = None,
        choices: Sequence[object] | None = None,
        required: bool = False,
        help: str | None = None,
        metavar: str | tuple[str, ...] | None = None,
    ) -> None:
        self._key = key
        self._const_value = const_value
        super().__init__(
            option_strings,
            dest,
            nargs=nargs,
            const=const,
            default=default,
            type=type,
            choices=choices,
            required=required,
            help=help,
            metavar=metavar,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[object] | None,
        option_string: str | None = None,
    ) -> None:
        raw_overrides = cast(object | None, getattr(namespace, "overrides", None))
        if raw_overrides is None:
            overrides: list[str] = []
        elif isinstance(raw_overrides, list):
            overrides = [str(item) for item in cast(list[object], raw_overrides)]
        else:
            overrides = [str(raw_overrides)]
        namespace.overrides = overrides

        if values is None:
            value = self._const_value if self._const_value is not None else "true"
        elif isinstance(values, str):
            value = values
        else:
            if len(values) == 0:
                value = self._const_value if self._const_value is not None else "true"
            else:
                value = ",".join(str(item) for item in values)
        overrides.append(f"{self._key}={value}")


def add_badguys_cli_args(parser: argparse.ArgumentParser) -> None:
    badguys_mode_choices: tuple[str, str] = ("auto", "always")
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
        choices=badguys_mode_choices,
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
