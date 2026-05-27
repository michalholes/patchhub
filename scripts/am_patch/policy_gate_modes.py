from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from .errors import RunnerError


class PolicyGateModesLike(Protocol):
    gate_ruff_mode: str
    gate_mypy_mode: str
    gate_pytest_mode: str
    gate_typescript_mode: str
    gate_badguys_mode: str
    gate_pytest_py_prefixes: list[str]
    gate_pytest_js_prefixes: list[str]
    gate_badguys_trigger_prefixes: list[str]
    gate_badguys_trigger_files: list[str]


def _normalize_prefixes(raw: object, *, code: str, key: str) -> list[str]:
    if isinstance(raw, str):
        prefixes = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, list):
        items = cast(list[object], raw)
        prefixes = [str(s).strip() for s in items]
    else:
        raise RunnerError(
            "CONFIG",
            code,
            f"{key} must be list[str] or CSV string",
        )

    norm: list[str] = []
    for s in prefixes:
        if not s:
            continue
        s = s.replace("\\", "/")
        if s.startswith("./"):
            s = s[2:]
        s = s.rstrip("/")
        if s:
            norm.append(s)

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in norm:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped


def apply_gate_modes(
    cfg: dict[str, object],
    p: PolicyGateModesLike,
    mark_cfg: Callable[[PolicyGateModesLike, dict[str, object], str], None],
) -> None:
    p.gate_ruff_mode = str(cfg.get("gate_ruff_mode", p.gate_ruff_mode)).strip()
    mark_cfg(p, cfg, "gate_ruff_mode")
    if p.gate_ruff_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_RUFF_MODE",
            f"invalid gate_ruff_mode: {p.gate_ruff_mode!r}",
        )

    p.gate_mypy_mode = str(cfg.get("gate_mypy_mode", p.gate_mypy_mode)).strip()
    mark_cfg(p, cfg, "gate_mypy_mode")
    if p.gate_mypy_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_MYPY_MODE",
            f"invalid gate_mypy_mode: {p.gate_mypy_mode!r}",
        )

    p.gate_pytest_mode = str(cfg.get("gate_pytest_mode", p.gate_pytest_mode)).strip()
    mark_cfg(p, cfg, "gate_pytest_mode")
    if p.gate_pytest_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_PYTEST_MODE",
            f"invalid gate_pytest_mode: {p.gate_pytest_mode!r}",
        )

    p.gate_typescript_mode = str(cfg.get("gate_typescript_mode", p.gate_typescript_mode)).strip()
    mark_cfg(p, cfg, "gate_typescript_mode")
    if p.gate_typescript_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_TYPESCRIPT_MODE",
            f"invalid gate_typescript_mode: {p.gate_typescript_mode!r}",
        )

    p.gate_badguys_mode = str(cfg.get("gate_badguys_mode", p.gate_badguys_mode)).strip()
    mark_cfg(p, cfg, "gate_badguys_mode")
    if p.gate_badguys_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_BADGUYS_MODE",
            f"invalid gate_badguys_mode: {p.gate_badguys_mode!r}",
        )

    raw = cfg.get("gate_pytest_py_prefixes", p.gate_pytest_py_prefixes)
    mark_cfg(p, cfg, "gate_pytest_py_prefixes")
    p.gate_pytest_py_prefixes = _normalize_prefixes(
        raw,
        code="INVALID_GATE_PYTEST_PY_PREFIXES",
        key="gate_pytest_py_prefixes",
    )

    raw = cfg.get("gate_pytest_js_prefixes", p.gate_pytest_js_prefixes)
    mark_cfg(p, cfg, "gate_pytest_js_prefixes")
    p.gate_pytest_js_prefixes = _normalize_prefixes(
        raw,
        code="INVALID_GATE_PYTEST_JS_PREFIXES",
        key="gate_pytest_js_prefixes",
    )

    raw = cfg.get("gate_badguys_trigger_prefixes", p.gate_badguys_trigger_prefixes)
    mark_cfg(p, cfg, "gate_badguys_trigger_prefixes")
    p.gate_badguys_trigger_prefixes = _normalize_prefixes(
        raw,
        code="INVALID_GATE_BADGUYS_TRIGGER_PREFIXES",
        key="gate_badguys_trigger_prefixes",
    )

    raw = cfg.get("gate_badguys_trigger_files", p.gate_badguys_trigger_files)
    mark_cfg(p, cfg, "gate_badguys_trigger_files")
    p.gate_badguys_trigger_files = _normalize_prefixes(
        raw,
        code="INVALID_GATE_BADGUYS_TRIGGER_FILES",
        key="gate_badguys_trigger_files",
    )
