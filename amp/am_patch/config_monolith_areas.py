from __future__ import annotations

from .errors import RunnerError


def parse_monolith_areas(cfg: dict[str, object]) -> tuple[list[str], list[str], list[str]]:
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

    if not (len(prefixes_raw) == len(names_raw) == len(dynamic_raw)):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "gate_monolith_areas lengths mismatch: "
            f"prefixes={len(prefixes_raw)} names={len(names_raw)} dynamic={len(dynamic_raw)}",
        )

    prefixes: list[str] = []
    names: list[str] = []
    dynamic: list[str] = []

    for i, s in enumerate(prefixes_raw):
        ps = str(s).strip()
        if ps == "":
            raise RunnerError("CONFIG", "INVALID", f"{prefixes_key}[{i}] must be non-empty")
        prefixes.append(ps)

    for i, s in enumerate(names_raw):
        ns = str(s).strip()
        if ns == "":
            raise RunnerError("CONFIG", "INVALID", f"{names_key}[{i}] must be non-empty")
        names.append(ns)

    for _i, s in enumerate(dynamic_raw):
        ds = str(s)
        dynamic.append(ds)

    return (prefixes, names, dynamic)
