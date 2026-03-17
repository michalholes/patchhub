from __future__ import annotations

from dataclasses import dataclass


class GateArgvError(ValueError):
    pass


@dataclass(frozen=True)
class GateOption:
    key: str
    cli_flag: str
    direct_true: bool


GATE_OPTIONS: tuple[GateOption, ...] = (
    GateOption("compile_check", "--no-compile-check", False),
    GateOption("gates_skip_dont_touch", "--skip-dont-touch", True),
    GateOption("gates_skip_ruff", "--skip-ruff", True),
    GateOption("gates_skip_pytest", "--skip-pytest", True),
    GateOption("gates_skip_mypy", "--skip-mypy", True),
    GateOption("gates_skip_js", "--skip-js", True),
    GateOption("gates_skip_docs", "--skip-docs", True),
    GateOption("gates_skip_monolith", "--skip-monolith", True),
    GateOption("gates_skip_biome", "--skip-biome", True),
    GateOption("gates_skip_typescript", "--skip-typescript", True),
)

_FLAG_TO_OPTION = {item.cli_flag: item for item in GATE_OPTIONS}
_KEY_TO_OPTION = {item.key: item for item in GATE_OPTIONS}


def _parse_bool_text(value: str) -> bool:
    norm = str(value or "").strip().lower()
    if norm == "true":
        return True
    if norm == "false":
        return False
    raise GateArgvError(f"Override value must be true/false (got {value})")


def _parse_override_pair(pair: str) -> tuple[str, bool]:
    text = str(pair or "").strip()
    if not text or "=" not in text:
        raise GateArgvError("--override requires KEY=VALUE")
    key, raw_value = text.split("=", 1)
    key = key.strip().lower()
    if key not in _KEY_TO_OPTION:
        raise GateArgvError(f"Unsupported gate override key: {key}")
    return key, _parse_bool_text(raw_value)


def build_gate_argv(states: dict[str, bool]) -> list[str]:
    argv: list[str] = []
    for item in GATE_OPTIONS:
        if item.key not in states:
            continue
        value = bool(states[item.key])
        if value == item.direct_true:
            argv.append(item.cli_flag)
            continue
        argv.extend(["--override", f"{item.key}={'true' if value else 'false'}"])
    return argv


def split_gate_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    states: dict[str, bool] = {}
    rest: list[str] = []
    idx = 0
    while idx < len(argv):
        token = str(argv[idx] or "")
        opt = _FLAG_TO_OPTION.get(token)
        if opt is not None:
            states[opt.key] = opt.direct_true
            idx += 1
            continue
        if token == "--override":
            if idx + 1 >= len(argv):
                raise GateArgvError("--override requires KEY=VALUE")
            key, value = _parse_override_pair(str(argv[idx + 1] or ""))
            states[key] = value
            idx += 2
            continue
        rest.append(token)
        idx += 1
    return rest, build_gate_argv(states)


def validate_gate_argv(argv: list[str]) -> list[str]:
    rest, canonical = split_gate_argv(list(argv))
    if rest:
        raise GateArgvError(f"Unexpected gate argv token: {rest[0]}")
    return canonical
