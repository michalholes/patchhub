from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from patchhub.app_support import err as err_response
from patchhub.app_support import ok as ok_response
from patchhub.config import AppConfig
from patchhub.fs_jail import FsJail


class AmpApiContext(Protocol):
    repo_root: Path
    cfg: AppConfig
    jail: FsJail


def _is_lock_held(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("a+")
    try:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            with contextlib.suppress(Exception):
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        fd.close()


def _runner_config_path(repo_root: Path, cfg: AppConfig) -> Path:
    rel = str(cfg.runner.runner_config_toml).strip()
    if not rel:
        raise ValueError("missing runner_config_toml")
    return (repo_root / rel).resolve()


runner_config_path = _runner_config_path


def _obj_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast(Mapping[object, object], value)
    out: dict[str, object] = {}
    for key, item in mapping.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _str_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in list(cast(list[object], value)):
        if not isinstance(item, str):
            return None
        out.append(item)
    return out


def _normalize_policy_value(value: object, default_value: object) -> object | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    value_list = _str_list(value)
    if value_list is not None:
        return value_list

    if value is None:
        if isinstance(default_value, bool):
            return False
        if isinstance(default_value, int) and not isinstance(default_value, bool):
            return 0
        if isinstance(default_value, str):
            return ""
        if _str_list(default_value) is not None:
            return []
        return None

    return None


def _policy_snapshot(policy_obj: object) -> dict[str, object]:
    raw_obj: object
    try:
        raw_obj = cast(object, policy_obj.__dict__)
    except Exception:
        return {}
    return _obj_dict(raw_obj) or {}


def _load_config_safe(cfg_path: Path) -> tuple[dict[str, object], bool]:
    from am_patch.config import load_config

    flat, used = load_config(cfg_path)
    return dict(flat), bool(used)


def _flatten_sections_safe(data: object) -> dict[str, object]:
    from am_patch.config import _flatten_sections

    return _flatten_sections(data)


def _policy_keys(policy_obj: object, allowed_keys: set[str] | None = None) -> list[str]:
    out: list[str] = []
    for key in _policy_snapshot(policy_obj):
        if key == "_src":
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
        out.append(str(key))
    return out


def _read_policy_values(
    cfg_path: Path,
    *,
    allowed_keys: set[str] | None = None,
) -> dict[str, object]:
    from am_patch.config import Policy, build_policy

    flat, ok = _load_config_safe(cfg_path)
    if not ok:
        flat = {}
    defaults = Policy()
    p = build_policy(defaults, flat)
    defaults_map = _policy_snapshot(defaults)
    current_map = _policy_snapshot(p)

    out: dict[str, object] = {}
    for key in _policy_keys(defaults, allowed_keys):
        normalized = _normalize_policy_value(
            current_map.get(key),
            defaults_map.get(key),
        )
        if normalized is not None:
            out[key] = normalized
    return out


def _read_policy_values_from_text(
    text: str,
    *,
    allowed_keys: set[str] | None = None,
) -> dict[str, object]:
    from am_patch.config import Policy, build_policy

    data: object = tomllib.loads(text)
    flat = _flatten_sections_safe(data)
    defaults = Policy()
    p = build_policy(defaults, flat)
    defaults_map = _policy_snapshot(defaults)
    current_map = _policy_snapshot(p)

    out: dict[str, object] = {}
    for key in _policy_keys(defaults, allowed_keys):
        normalized = _normalize_policy_value(
            current_map.get(key),
            defaults_map.get(key),
        )
        if normalized is not None:
            out[key] = normalized
    return out


def api_amp_schema(self: AmpApiContext) -> tuple[int, bytes]:
    from am_patch.config_schema import get_bootstrap_policy_schema

    schema = get_bootstrap_policy_schema()
    policy = schema.get("policy")
    policy_map = _obj_dict(policy)
    if policy_map is None:
        return err_response("amp_schema_invalid: policy missing")

    allowed_types = {"bool", "int", "str", "optional[str]", "list[str]"}
    editable: dict[str, object] = {}
    for key, item in policy_map.items():
        if key == "json_out":
            continue
        item_map = _obj_dict(item)
        if item_map is None:
            return err_response(f"amp_schema_invalid: invalid item for {key}")
        if item_map.get("read_only") is True:
            continue
        if str(item_map.get("type") or "") not in allowed_types:
            continue
        editable[key] = item_map

    schema["policy"] = editable
    return ok_response({"schema": schema})


def api_amp_config_get(self: AmpApiContext) -> tuple[int, bytes]:
    try:
        cfg_path = _runner_config_path(self.repo_root, self.cfg)
        from am_patch.config import BOOTSTRAP_OWNED_KEYS

        values = _read_policy_values(cfg_path, allowed_keys=BOOTSTRAP_OWNED_KEYS)
        values.pop("json_out", None)
    except Exception as e:
        return err_response(f"amp_config_read_failed: {type(e).__name__}: {e}")
    return ok_response({"values": values})


def api_amp_config_post(self: AmpApiContext, body: dict[str, object]) -> tuple[int, bytes]:
    if _is_lock_held(self.jail.lock_path()):
        return err_response("Runner active (lock held)", status=409)

    values = _obj_dict(body.get("values"))
    if values is None:
        return err_response("values must be an object")
    dry_run = bool(body.get("dry_run", False))
    if "json_out" in values:
        return err_response("json_out is PatchHub-managed and cannot be changed")

    from am_patch.config import BOOTSTRAP_OWNED_KEYS
    from am_patch.config_edit import (
        apply_update_to_config_text,
        validate_config_text_roundtrip,
        validate_patchhub_update,
    )
    from am_patch.config_schema import get_bootstrap_policy_schema
    from am_patch.errors import RunnerError

    schema = get_bootstrap_policy_schema()
    try:
        updates_typed = validate_patchhub_update(values, schema)

        cfg_path = _runner_config_path(self.repo_root, self.cfg)
        original_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""

        new_text = apply_update_to_config_text(original_text, updates_typed, schema)
        validate_config_text_roundtrip(new_text)

        if dry_run:
            # Dry-run must validate without applying (and without writing).
            typed = _read_policy_values_from_text(new_text, allowed_keys=BOOTSTRAP_OWNED_KEYS)
        else:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=cfg_path.name + ".tmp.",
                dir=str(cfg_path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out_fp:
                    out_fp.write(new_text)
                os.replace(tmp_name, cfg_path)
            finally:
                try:
                    if os.path.exists(tmp_name):
                        os.unlink(tmp_name)
                except Exception:
                    pass

            typed = _read_policy_values(cfg_path, allowed_keys=BOOTSTRAP_OWNED_KEYS)
    except RunnerError as e:
        return err_response(f"amp_config_invalid: {e}")
    except Exception as e:
        return err_response(f"amp_config_update_failed: {type(e).__name__}: {e}")

    updated = sorted(updates_typed.keys())
    return ok_response({"dry_run": dry_run, "values": typed, "updated": updated})
