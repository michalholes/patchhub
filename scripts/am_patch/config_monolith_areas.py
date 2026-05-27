from __future__ import annotations

from typing import cast

from .errors import RunnerError


def parse_monolith_areas(
    cfg: dict[str, object],
) -> tuple[list[str], list[str], list[str]]:
    """Parse and validate monolith ownership areas configuration.

    Contract:
    - Legacy key ``gate_monolith_areas`` is forbidden (hard error if present).
    - The new keys are optional as a group. If none of the new keys are present,
      this returns three empty lists (defaults stay in effect).
    - If any of the new keys are present, all three must be present and must be
      list-like with identical lengths.
    - ``prefixes`` and ``names`` entries must be non-empty after stripping.
    - ``dynamic`` entries are stored as strings; empty/whitespace entries are allowed.
    """

    if "gate_monolith_areas" in cfg:
        raise RunnerError(
            "CONFIG", "INVALID", "legacy config key is forbidden: gate_monolith_areas"
        )

    prefixes_key = "gate_monolith_areas_prefixes"
    names_key = "gate_monolith_areas_names"
    dynamic_key = "gate_monolith_areas_dynamic"

    any_new = any(k in cfg for k in (prefixes_key, names_key, dynamic_key))
    if not any_new:
        return ([], [], [])

    missing = [k for k in (prefixes_key, names_key, dynamic_key) if k not in cfg]
    if missing:
        # Keep message deterministic for tests / UX.
        raise RunnerError("CONFIG", "INVALID", f"missing config key: {missing[0]}")

    prefixes_raw = cfg[prefixes_key]
    names_raw = cfg[names_key]
    dynamic_raw = cfg[dynamic_key]

    if not isinstance(prefixes_raw, list):
        raise RunnerError("CONFIG", "INVALID", f"{prefixes_key} must be a list")
    if not isinstance(names_raw, list):
        raise RunnerError("CONFIG", "INVALID", f"{names_key} must be a list")
    if not isinstance(dynamic_raw, list):
        raise RunnerError("CONFIG", "INVALID", f"{dynamic_key} must be a list")

    prefixes_items = cast(list[object], prefixes_raw)
    names_items = cast(list[object], names_raw)
    dynamic_items = cast(list[object], dynamic_raw)

    if not (len(prefixes_items) == len(names_items) == len(dynamic_items)):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "gate_monolith_areas lengths mismatch: "
            f"prefixes={len(prefixes_items)} names={len(names_items)} dynamic={len(dynamic_items)}",
        )

    prefixes: list[str] = []
    names: list[str] = []
    dynamic: list[str] = []

    for i, item in enumerate(prefixes_items):
        ps = str(item).strip()
        if ps == "":
            raise RunnerError("CONFIG", "INVALID", f"{prefixes_key}[{i}] must be non-empty")
        prefixes.append(ps)

    for i, item in enumerate(names_items):
        ns = str(item).strip()
        if ns == "":
            raise RunnerError("CONFIG", "INVALID", f"{names_key}[{i}] must be non-empty")
        names.append(ns)

    for item in dynamic_items:
        ds = str(item)
        dynamic.append(ds)

    return (prefixes, names, dynamic)
