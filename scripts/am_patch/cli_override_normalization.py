from __future__ import annotations

from typing import Any


def apply_explicit_gate_flag_overrides(ns: Any) -> None:
    """Map explicit gate CLI flags into override entries in argv order."""

    if getattr(ns, "skip_dont_touch", None):
        ns.overrides = (ns.overrides or []) + ["gates_skip_dont_touch=true"]
    if getattr(ns, "skip_biome", None):
        ns.overrides = (ns.overrides or []) + ["gates_skip_biome=true"]
    if getattr(ns, "skip_typescript", None):
        ns.overrides = (ns.overrides or []) + ["gates_skip_typescript=true"]

    if getattr(ns, "gate_biome_extensions", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_biome_extensions={str(ns.gate_biome_extensions).strip()}"
        ]
    if getattr(ns, "biome_autofix", None) is not None:
        value = "true" if bool(ns.biome_autofix) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_autofix={value}"]
    if getattr(ns, "biome_format", None) is not None:
        value = "true" if bool(ns.biome_format) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_format={value}"]
    if getattr(ns, "biome_autofix_legalize_outside", None) is not None:
        value = "true" if bool(ns.biome_autofix_legalize_outside) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_autofix_legalize_outside={value}"]
    if getattr(ns, "biome_format_legalize_outside", None) is not None:
        value = "true" if bool(ns.biome_format_legalize_outside) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_format_legalize_outside={value}"]
    if getattr(ns, "gate_biome_command", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_biome_command={str(ns.gate_biome_command).strip()}"
        ]
    if getattr(ns, "gate_biome_fix_command", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_biome_fix_command={str(ns.gate_biome_fix_command).strip()}"
        ]
    if getattr(ns, "gate_biome_format_command", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_biome_format_command={str(ns.gate_biome_format_command).strip()}"
        ]
    if getattr(ns, "gate_typescript_extensions", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_typescript_extensions={str(ns.gate_typescript_extensions).strip()}"
        ]
    if getattr(ns, "gate_typescript_command", None) is not None:
        ns.overrides = (ns.overrides or []) + [
            f"gate_typescript_command={str(ns.gate_typescript_command).strip()}"
        ]


def build_cli_override_mapping(cli: Any) -> dict[str, object | None]:
    return {
        "run_all_tests": getattr(cli, "run_all_tests", None),
        "verbosity": getattr(cli, "verbosity", None),
        "log_level": getattr(cli, "log_level", None),
        "json_out": getattr(cli, "json_out", None),
        "console_color": getattr(cli, "console_color", None),
        "allow_no_op": getattr(cli, "allow_no_op", None),
        "skip_up_to_date": getattr(cli, "skip_up_to_date", None),
        "allow_non_main": getattr(cli, "allow_non_main", None),
        "no_rollback": getattr(cli, "no_rollback", None),
        "success_archive_name": getattr(cli, "success_archive_name", None),
        "update_workspace": getattr(cli, "update_workspace", None),
        "gates_allow_fail": getattr(cli, "allow_gates_fail", None),
        "gates_skip_ruff": getattr(cli, "skip_ruff", None),
        "gates_skip_pytest": getattr(cli, "skip_pytest", None),
        "gates_skip_mypy": getattr(cli, "skip_mypy", None),
        "gates_skip_js": getattr(cli, "skip_js", None),
        "gates_skip_docs": getattr(cli, "skip_docs", None),
        "gates_skip_monolith": getattr(cli, "skip_monolith", None),
        "apply_failure_partial_gates_policy": getattr(
            cli, "apply_failure_partial_gates_policy", None
        ),
        "apply_failure_zero_gates_policy": getattr(cli, "apply_failure_zero_gates_policy", None),
        "gates_order": (
            []
            if (
                getattr(cli, "gates_order", None) is not None and str(cli.gates_order).strip() == ""
            )
            else [s.strip().lower() for s in str(cli.gates_order).split(",") if s.strip()]
            if getattr(cli, "gates_order", None) is not None
            else None
        ),
        "gate_docs_include": (
            []
            if (
                getattr(cli, "docs_include", None) is not None
                and str(cli.docs_include).strip() == ""
            )
            else [s.strip() for s in str(cli.docs_include).split(",") if s.strip()]
            if getattr(cli, "docs_include", None) is not None
            else None
        ),
        "gate_docs_exclude": (
            []
            if (
                getattr(cli, "docs_exclude", None) is not None
                and str(cli.docs_exclude).strip() == ""
            )
            else [s.strip() for s in str(cli.docs_exclude).split(",") if s.strip()]
            if getattr(cli, "docs_exclude", None) is not None
            else None
        ),
        "ruff_autofix_legalize_outside": getattr(cli, "ruff_autofix_legalize_outside", None),
        "soft_reset_workspace": getattr(cli, "soft_reset_workspace", None),
        "enforce_allowed_files": getattr(cli, "enforce_allowed_files", None),
        "rollback_workspace_on_fail": getattr(cli, "rollback_workspace_on_fail", None),
        "live_repo_guard": getattr(cli, "live_repo_guard", None),
        "live_repo_guard_scope": getattr(cli, "live_repo_guard_scope", None),
        "patch_jail": getattr(cli, "patch_jail", None),
        "patch_jail_unshare_net": getattr(cli, "patch_jail_unshare_net", None),
        "ruff_format": getattr(cli, "ruff_format", None),
        "pytest_use_venv": getattr(cli, "pytest_use_venv", None),
        "compile_check": getattr(cli, "compile_check", None),
        "post_success_audit": getattr(cli, "post_success_audit", None),
        "test_mode": getattr(cli, "test_mode", None),
        "unified_patch": getattr(cli, "unified_patch", None),
        "unified_patch_strip": getattr(cli, "patch_strip", None),
        "overrides": getattr(cli, "overrides", None),
    }


def apply_cli_symmetry_helpers(policy: Any, cli: Any) -> None:
    if getattr(cli, "require_push_success", None):
        policy.allow_push_fail = False
        policy._src["allow_push_fail"] = "cli"
    if getattr(cli, "disable_promotion", None):
        policy.commit_and_push = False
        policy._src["commit_and_push"] = "cli"
    if getattr(cli, "allow_live_changed", None):
        policy.fail_if_live_files_changed = False
        policy._src["fail_if_live_files_changed"] = "cli"
        policy.live_changed_resolution = "overwrite_live"
        policy._src["live_changed_resolution"] = "cli"
    if getattr(cli, "keep_workspace", None):
        policy.delete_workspace_on_success = False
        policy._src["delete_workspace_on_success"] = "cli"
    if getattr(cli, "allow_outside_files", None):
        policy.allow_outside_files = True
        policy._src["allow_outside_files"] = "cli"
    if getattr(cli, "allow_declared_untouched", None):
        policy.allow_declared_untouched = True
        policy._src["allow_declared_untouched"] = "cli"
