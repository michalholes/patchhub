from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import RunnerError


def _normalize_prefixes(raw: object, *, code: str, key: str) -> list[str]:
    if isinstance(raw, str):
        prefixes = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, list):
        prefixes = [str(s).strip() for s in raw]
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

    return list(dict.fromkeys(norm))


def apply_gate_modes(
    cfg: dict[str, Any],
    p: Any,
    mark_cfg: Callable[[Any, dict[str, Any], str], None],
) -> None:
    for k, code in (
        ("gate_ruff_mode", "INVALID_GATE_RUFF_MODE"),
        ("gate_mypy_mode", "INVALID_GATE_MYPY_MODE"),
        ("gate_pytest_mode", "INVALID_GATE_PYTEST_MODE"),
        ("gate_typescript_mode", "INVALID_GATE_TYPESCRIPT_MODE"),
    ):
        v = str(cfg.get(k, getattr(p, k))).strip()
        setattr(p, k, v)
        mark_cfg(p, cfg, k)
        if v not in ("auto", "always"):
            raise RunnerError("CONFIG", code, f"invalid {k}: {v!r}")

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
