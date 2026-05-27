from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import cast

from badguys.bdg_loader import BdgTest

_BASE_CFG_KEYS = ("suite", "lock", "guard", "filters", "runner")
_BUILD_CFG_STEP_RECIPE_KEYS = {
    "commit_limit",
    "console_verbosity",
    "log_verbosity",
    "runner_verbosity",
}
_RUN_RUNNER_STEP_RECIPE_KEYS = {"args"}
_RAW_CACHE: dict[tuple[str, str], dict[str, object]] = {}


def _config_relpath(config_path: Path | str) -> str:
    path = Path(config_path)
    return path.as_posix()


def _load_raw(repo_root_str: str, config_relpath: str) -> dict[str, object]:
    cache_key = (repo_root_str, config_relpath)
    cached = _RAW_CACHE.get(cache_key)
    if cached is not None:
        return cached

    repo_root = Path(repo_root_str)
    path = repo_root / Path(config_relpath)
    raw = cast(object, tomllib.loads(path.read_text(encoding="utf-8")))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, object] = {}
    for key, value in cast(dict[object, object], raw).items():
        out[str(key)] = value
    _RAW_CACHE[cache_key] = out
    return out


def _raw(*, repo_root: Path, config_path: Path | str) -> dict[str, object]:
    return _load_raw(str(repo_root), _config_relpath(config_path))


def _copy_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        out[str(key)] = deepcopy(item)
    return out


def ensure_allowed_keys(*, table: dict[str, object], allowed: set[str], label: str) -> None:
    extra = sorted(set(table) - allowed)
    if extra:
        joined = ", ".join(extra)
        raise SystemExit(f"FAIL: bdg recipe: {label} has unknown keys: {joined}")


def _tests_table(raw: dict[str, object], section_name: str) -> dict[str, object]:
    section = raw.get(section_name, {})
    if not isinstance(section, dict):
        return {}
    tests = cast(dict[object, object], section).get("tests", {})
    return _copy_dict(tests)


def _test_recipe(raw: dict[str, object], test_id: str) -> dict[str, object]:
    return _copy_dict(_tests_table(raw, "recipes").get(test_id, {}))


def base_cfg_sections(*, repo_root: Path, config_path: Path | str) -> dict[str, object]:
    raw = _raw(repo_root=repo_root, config_path=config_path)
    return {key: _copy_dict(raw.get(key, {})) for key in _BASE_CFG_KEYS}


def step_recipe(
    *,
    repo_root: Path,
    config_path: Path | str,
    test_id: str,
    step_index: int,
) -> dict[str, object]:
    recipe = _test_recipe(_raw(repo_root=repo_root, config_path=config_path), test_id)
    steps_obj = recipe.get("steps", {})
    if not isinstance(steps_obj, dict):
        return {}
    steps = cast(dict[object, object], steps_obj)
    key_str = str(step_index)
    item = steps.get(key_str) if key_str in steps else steps.get(step_index)
    if item is None:
        return {}
    if not isinstance(item, dict):
        raise SystemExit(
            f"FAIL: bdg recipe: recipes.tests.{test_id}.steps.{step_index} must be a table"
        )
    return _copy_dict(cast(dict[object, object], item))


def _legacy_subjects(raw: dict[str, object], test_id: str) -> dict[str, object]:
    table = _tests_table(raw, "subjects").get(test_id, {})
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise SystemExit(f"FAIL: bdg recipe: subjects.tests.{test_id} must be a table")
    return _copy_dict(cast(dict[object, object], table))


def _legacy_assets(raw: dict[str, object], test_id: str) -> dict[str, object]:
    recipe = _test_recipe(raw, test_id)
    assets = recipe.get("assets", {})
    if assets is None:
        return {}
    if not isinstance(assets, dict):
        raise SystemExit(f"FAIL: bdg recipe: recipes.tests.{test_id}.assets must be a table")
    return _copy_dict(cast(dict[object, object], assets))


def _allowed_step_recipe_keys_for_op(op: str) -> set[str]:
    if op == "RUN_RUNNER":
        return set(_RUN_RUNNER_STEP_RECIPE_KEYS)
    if op == "BUILD_CFG":
        return set(_BUILD_CFG_STEP_RECIPE_KEYS)
    return set()


def validate_test_config_boundary(
    *,
    repo_root: Path,
    config_path: Path | str,
    bdg: BdgTest,
) -> None:
    raw = _raw(repo_root=repo_root, config_path=config_path)
    test_id = bdg.test_id

    legacy_subjects = _legacy_subjects(raw, test_id)
    if legacy_subjects:
        raise SystemExit(
            f"FAIL: bdg recipe: per-test [subjects] moved to .bdg; remove subjects.tests.{test_id}"
        )

    legacy_assets = _legacy_assets(raw, test_id)
    if legacy_assets:
        raise SystemExit(
            "FAIL: bdg recipe: per-test asset materialization moved to .bdg; "
            f"remove recipes.tests.{test_id}.assets"
        )

    recipe = _test_recipe(raw, test_id)
    ensure_allowed_keys(
        table=recipe,
        allowed={"steps"},
        label=f"recipes.tests.{test_id}",
    )
    steps = recipe.get("steps", {})
    if not isinstance(steps, dict):
        raise SystemExit(f"FAIL: bdg recipe: recipes.tests.{test_id}.steps must be a table")

    for key, item in cast(dict[object, object], steps).items():
        if isinstance(key, str) and key.isdigit():
            step_index = int(key)
        elif isinstance(key, int):
            step_index = key
        else:
            raise SystemExit(
                f"FAIL: bdg recipe: recipes.tests.{test_id}.steps keys must be integers"
            )
        if step_index < 0 or step_index >= len(bdg.steps):
            raise SystemExit(
                f"FAIL: bdg recipe: stale step recipe entry for {test_id} step {step_index}"
            )
        if not isinstance(item, dict):
            raise SystemExit(
                f"FAIL: bdg recipe: recipes.tests.{test_id}.steps.{step_index} must be a table"
            )
        item_table = _copy_dict(cast(dict[object, object], item))
        allowed = _allowed_step_recipe_keys_for_op(bdg.steps[step_index].op)
        ensure_allowed_keys(
            table=item_table,
            allowed=allowed,
            label=f"recipes.tests.{test_id}.steps.{step_index}",
        )
        if not allowed and item_table:
            raise SystemExit(
                "FAIL: bdg recipe: non-runner step recipe moved to .bdg; "
                f"remove recipes.tests.{test_id}.steps.{step_index}"
            )
