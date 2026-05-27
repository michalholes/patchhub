from __future__ import annotations

from typing import Protocol, cast


class _OverridesLike(Protocol):
    overrides: list[str] | None


class _PolicyCliSymmetryLike(Protocol):
    allow_push_fail: bool
    commit_and_push: bool
    fail_if_live_files_changed: bool
    live_changed_resolution: str
    delete_workspace_on_success: bool
    allow_outside_files: bool
    allow_declared_untouched: bool


def _get_attr(obj: object, name: str) -> object | None:
    return cast(object | None, getattr(obj, name, None))


def _append_override(ns: object, entry: str) -> None:
    ns_obj = cast(_OverridesLike, ns)
    raw_overrides = _get_attr(ns, "overrides")
    if raw_overrides is None:
        overrides: list[str] = []
    elif isinstance(raw_overrides, list):
        overrides = [str(item) for item in cast(list[object], raw_overrides)]
    else:
        overrides = [str(raw_overrides)]
    overrides.append(entry)
    ns_obj.overrides = overrides


def _flag_enabled(obj: object, name: str) -> bool:
    return bool(_get_attr(obj, name))


def _csv_values(raw: object | None, *, lower: bool = False) -> list[str] | None:
    if raw is None:
        return None
    text = str(raw)
    if text.strip() == "":
        return []
    out = [chunk.strip() for chunk in text.split(",") if chunk.strip()]
    if lower:
        return [item.lower() for item in out]
    return out


def _set_policy_src(policy: object, key: str) -> None:
    raw_src = _get_attr(policy, "_src")
    if not isinstance(raw_src, dict):
        return
    src_map = cast(dict[object, object], raw_src)
    src_map[key] = "cli"


def apply_explicit_gate_flag_overrides(ns: object) -> None:
    """Map explicit gate CLI flags into override entries in argv order."""

    if _flag_enabled(ns, "skip_dont_touch"):
        _append_override(ns, "gates_skip_dont_touch=true")
    if _flag_enabled(ns, "skip_biome"):
        _append_override(ns, "gates_skip_biome=true")
    if _flag_enabled(ns, "skip_typescript"):
        _append_override(ns, "gates_skip_typescript=true")

    raw = _get_attr(ns, "gate_biome_extensions")
    if raw is not None:
        _append_override(ns, f"gate_biome_extensions={str(raw).strip()}")

    raw = _get_attr(ns, "biome_autofix")
    if raw is not None:
        value = "true" if bool(raw) else "false"
        _append_override(ns, f"biome_autofix={value}")

    raw = _get_attr(ns, "biome_format")
    if raw is not None:
        value = "true" if bool(raw) else "false"
        _append_override(ns, f"biome_format={value}")

    raw = _get_attr(ns, "biome_autofix_legalize_outside")
    if raw is not None:
        value = "true" if bool(raw) else "false"
        _append_override(ns, f"biome_autofix_legalize_outside={value}")

    raw = _get_attr(ns, "biome_format_legalize_outside")
    if raw is not None:
        value = "true" if bool(raw) else "false"
        _append_override(ns, f"biome_format_legalize_outside={value}")

    raw = _get_attr(ns, "gate_biome_command")
    if raw is not None:
        _append_override(ns, f"gate_biome_command={str(raw).strip()}")

    raw = _get_attr(ns, "gate_biome_fix_command")
    if raw is not None:
        _append_override(ns, f"gate_biome_fix_command={str(raw).strip()}")

    raw = _get_attr(ns, "gate_biome_format_command")
    if raw is not None:
        _append_override(ns, f"gate_biome_format_command={str(raw).strip()}")

    raw = _get_attr(ns, "gate_typescript_extensions")
    if raw is not None:
        _append_override(ns, f"gate_typescript_extensions={str(raw).strip()}")

    raw = _get_attr(ns, "gate_typescript_command")
    if raw is not None:
        _append_override(ns, f"gate_typescript_command={str(raw).strip()}")


def build_cli_override_mapping(cli: object) -> dict[str, object | None]:
    gates_order = _csv_values(_get_attr(cli, "gates_order"), lower=True)
    docs_include = _csv_values(_get_attr(cli, "docs_include"))
    docs_exclude = _csv_values(_get_attr(cli, "docs_exclude"))
    return {
        "run_all_tests": _get_attr(cli, "run_all_tests"),
        "verbosity": _get_attr(cli, "verbosity"),
        "log_level": _get_attr(cli, "log_level"),
        "json_out": _get_attr(cli, "json_out"),
        "console_color": _get_attr(cli, "console_color"),
        "allow_no_op": _get_attr(cli, "allow_no_op"),
        "skip_up_to_date": _get_attr(cli, "skip_up_to_date"),
        "allow_non_main": _get_attr(cli, "allow_non_main"),
        "no_rollback": _get_attr(cli, "no_rollback"),
        "success_archive_name": _get_attr(cli, "success_archive_name"),
        "update_workspace": _get_attr(cli, "update_workspace"),
        "gates_allow_fail": _get_attr(cli, "allow_gates_fail"),
        "gates_skip_ruff": _get_attr(cli, "skip_ruff"),
        "gates_skip_pytest": _get_attr(cli, "skip_pytest"),
        "gates_skip_mypy": _get_attr(cli, "skip_mypy"),
        "gates_skip_js": _get_attr(cli, "skip_js"),
        "gates_skip_docs": _get_attr(cli, "skip_docs"),
        "gates_skip_monolith": _get_attr(cli, "skip_monolith"),
        "apply_failure_partial_gates_policy": _get_attr(
            cli,
            "apply_failure_partial_gates_policy",
        ),
        "apply_failure_zero_gates_policy": _get_attr(
            cli,
            "apply_failure_zero_gates_policy",
        ),
        "gates_order": gates_order,
        "gate_docs_include": docs_include,
        "gate_docs_exclude": docs_exclude,
        "ruff_autofix_legalize_outside": _get_attr(
            cli,
            "ruff_autofix_legalize_outside",
        ),
        "soft_reset_workspace": _get_attr(cli, "soft_reset_workspace"),
        "enforce_allowed_files": _get_attr(cli, "enforce_allowed_files"),
        "rollback_workspace_on_fail": _get_attr(cli, "rollback_workspace_on_fail"),
        "live_repo_guard": _get_attr(cli, "live_repo_guard"),
        "live_repo_guard_scope": _get_attr(cli, "live_repo_guard_scope"),
        "patch_jail": _get_attr(cli, "patch_jail"),
        "patch_jail_unshare_net": _get_attr(cli, "patch_jail_unshare_net"),
        "ruff_format": _get_attr(cli, "ruff_format"),
        "pytest_use_venv": _get_attr(cli, "pytest_use_venv"),
        "compile_check": _get_attr(cli, "compile_check"),
        "post_success_audit": _get_attr(cli, "post_success_audit"),
        "test_mode": _get_attr(cli, "test_mode"),
        "unified_patch": _get_attr(cli, "unified_patch"),
        "unified_patch_strip": _get_attr(cli, "patch_strip"),
        "overrides": _get_attr(cli, "overrides"),
    }


def apply_cli_symmetry_helpers(policy: object, cli: object) -> None:
    policy_obj = cast(_PolicyCliSymmetryLike, policy)
    if _flag_enabled(cli, "require_push_success"):
        policy_obj.allow_push_fail = False
        _set_policy_src(policy, "allow_push_fail")
    if _flag_enabled(cli, "disable_promotion"):
        policy_obj.commit_and_push = False
        _set_policy_src(policy, "commit_and_push")
    if _flag_enabled(cli, "allow_live_changed"):
        policy_obj.fail_if_live_files_changed = False
        _set_policy_src(policy, "fail_if_live_files_changed")
        policy_obj.live_changed_resolution = "overwrite_live"
        _set_policy_src(policy, "live_changed_resolution")
    if _flag_enabled(cli, "keep_workspace"):
        policy_obj.delete_workspace_on_success = False
        _set_policy_src(policy, "delete_workspace_on_success")
    if _flag_enabled(cli, "allow_outside_files"):
        policy_obj.allow_outside_files = True
        _set_policy_src(policy, "allow_outside_files")
    if _flag_enabled(cli, "allow_declared_untouched"):
        policy_obj.allow_declared_untouched = True
        _set_policy_src(policy, "allow_declared_untouched")
