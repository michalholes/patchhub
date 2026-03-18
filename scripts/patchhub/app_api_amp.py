from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any, cast, get_args, get_origin, get_type_hints

from patchhub.app_support import _err, _json_bytes, _ok


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


def _runner_config_path(repo_root: Path, cfg: Any) -> Path:
    rel = str(getattr(getattr(cfg, "runner", object()), "runner_config_toml", "")).strip()
    if not rel:
        raise ValueError("missing runner_config_toml")
    return (repo_root / rel).resolve()


def _norm_type(tp: object) -> str | None:
    # Policy fields use plain types and optionals (e.g., str | None).
    # We support: bool, int, str, list[str] (and Optional variants of them).
    if tp in (bool, int, str):
        return cast(str, getattr(tp, "__name__", None))

    origin = get_origin(tp)
    args = get_args(tp)

    # Optional[T] / Union[T, None]
    if origin is None and args:
        # PEP 604 union types may expose args without origin.
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1:
            return _norm_type(non_none[0])

    if origin in (list,) and len(args) == 1 and args[0] is str:
        return "list_str"

    return None


def _read_policy_values(cfg_path: Path) -> dict[str, Any]:
    from am_patch.config import Policy, build_policy, load_config

    tmap = get_type_hints(Policy)

    flat, ok = load_config(cfg_path)
    if not ok:
        flat = {}
    p = build_policy(Policy(), flat)

    out: dict[str, Any] = {}
    for f in fields(Policy):
        if f.name == "_src":
            continue
        tp = tmap.get(f.name, f.type)
        norm = _norm_type(tp)
        if norm is None:
            continue
        v = getattr(p, f.name)
        if v is None:
            if norm in ("str",):
                v = ""
            elif norm == "list_str":
                v = []
            elif norm == "bool":
                v = False
            elif norm == "int":
                v = 0
        out[f.name] = v
    return out


def _read_policy_values_from_text(text: str) -> dict[str, Any]:
    from am_patch.config import Policy, _flatten_sections, build_policy

    tmap = get_type_hints(Policy)

    data = tomllib.loads(text)
    flat = _flatten_sections(data)
    p = build_policy(Policy(), flat)

    out: dict[str, Any] = {}
    for f in fields(Policy):
        if f.name == "_src":
            continue
        tp = tmap.get(f.name, f.type)
        norm = _norm_type(tp)
        if norm is None:
            continue
        v = getattr(p, f.name)
        if v is None:
            if norm in ("str",):
                v = ""
            elif norm == "list_str":
                v = []
            elif norm == "bool":
                v = False
            elif norm == "int":
                v = 0
        out[f.name] = v
    return out


def api_amp_schema(self) -> tuple[int, bytes]:
    from am_patch.config_schema import get_policy_schema

    schema = get_policy_schema()
    policy = schema.get("policy")
    if not isinstance(policy, dict):
        return _err("amp_schema_invalid: policy missing")

    allowed_types = {"bool", "int", "str", "optional[str]", "list[str]"}
    editable: dict[str, Any] = {}
    for key, item in policy.items():
        if key == "json_out":
            continue
        if not isinstance(item, dict):
            return _err(f"amp_schema_invalid: invalid item for {key}")
        if item.get("read_only") is True:
            continue
        if str(item.get("type") or "") not in allowed_types:
            continue
        editable[key] = item

    schema["policy"] = editable
    return _ok({"schema": schema})


def api_amp_config_get(self) -> tuple[int, bytes]:
    try:
        cfg_path = _runner_config_path(self.repo_root, self.cfg)
        values = _read_policy_values(cfg_path)
        values.pop("json_out", None)
    except Exception as e:
        return _err(f"amp_config_read_failed: {type(e).__name__}: {e}")
    return _ok({"values": values})


def api_amp_config_post(self, body: dict[str, Any]) -> tuple[int, bytes]:
    if _is_lock_held(self.jail.lock_path()):
        return _json_bytes({"ok": False, "error": "Runner active (lock held)"}, status=409)

    values = body.get("values")
    if not isinstance(values, dict):
        return _err("values must be an object")
    dry_run = bool(body.get("dry_run", False))
    if "json_out" in values:
        return _err("json_out is PatchHub-managed and cannot be changed")

    from am_patch.config_edit import (
        apply_update_to_config_text,
        validate_config_text_roundtrip,
        validate_patchhub_update,
    )
    from am_patch.config_schema import get_policy_schema
    from am_patch.errors import RunnerError

    schema = get_policy_schema()
    try:
        updates_typed = validate_patchhub_update(values, schema)

        cfg_path = _runner_config_path(self.repo_root, self.cfg)
        original_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""

        new_text = apply_update_to_config_text(original_text, updates_typed, schema)
        validate_config_text_roundtrip(new_text)

        if dry_run:
            # Dry-run must validate without applying (and without writing).
            typed = _read_policy_values_from_text(new_text)
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

            typed = _read_policy_values(cfg_path)
    except RunnerError as e:
        return _err(f"amp_config_invalid: {e}")
    except Exception as e:
        return _err(f"amp_config_update_failed: {type(e).__name__}: {e}")

    updated = sorted(updates_typed.keys())
    return _ok({"dry_run": dry_run, "values": typed, "updated": updated})
