"""Authoritative AMP policy schema export.

This module provides a deterministic, explicit schema describing the runner Policy
surface that PatchHub may edit.

The schema is derived from dataclasses.fields(Policy) but uses explicit mapping
tables for:
- TOML section placement
- field type categories used by the PatchHub editor
- enum allow-lists

No heuristics are permitted.
"""

from __future__ import annotations

from dataclasses import Field, fields
from typing import Any, get_args, get_origin, get_type_hints

from am_patch.config import Policy

SCHEMA_VERSION = "6"


# Explicit mapping of policy keys to TOML sections.
# Section "" means top-level (no [section] header).
_SECTION_BY_KEY: dict[str, str] = {
    # top-level
    "repo_root": "paths",
    "artifacts_root": "paths",
    "target_repo_roots": "paths",
    "active_target_repo_root": "paths",
    "patch_dir": "",
    "target_repo_name": "",
    "verbosity": "",
    "log_level": "",
    "runner_subprocess_timeout_s": "",
    "json_out": "",
    "console_color": "",
    "ipc_socket_enabled": "",
    "ipc_socket_mode": "",
    "ipc_socket_path": "",
    "ipc_socket_name_template": "",
    "ipc_socket_name": "",
    "ipc_socket_base_dir": "",
    "ipc_socket_system_runtime_dir": "",
    "ipc_socket_cleanup_delay_success_s": "",
    "ipc_socket_cleanup_delay_failure_s": "",
    "ipc_socket_on_startup_exists": "",
    "ipc_socket_on_startup_wait_s": "",
    "ipc_handshake_enabled": "",
    "ipc_handshake_wait_s": "",
    "unified_patch": "",
    "unified_patch_continue": "",
    "unified_patch_strip": "",
    "unified_patch_touch_on_fail": "",
    "no_op_fail": "",
    "allow_no_op": "",
    "enforce_allowed_files": "",
    "run_all_tests": "",
    "compile_check": "",
    "compile_targets": "",
    "compile_exclude": "",
    "ruff_autofix": "",
    "ruff_autofix_legalize_outside": "",
    "ruff_format": "",
    "biome_format": "",
    "biome_format_legalize_outside": "",
    "gate_biome_format_command": "",
    "gates_allow_fail": "",
    "gates_skip_dont_touch": "",
    "dont_touch_paths": "",
    "gates_skip_ruff": "",
    "gates_skip_pytest": "",
    "gates_skip_mypy": "",
    "gates_skip_docs": "",
    "gates_skip_monolith": "",
    "gates_skip_js": "",
    "gate_js_extensions": "",
    "gate_js_command": "",
    "gates_skip_biome": "",
    "gate_biome_extensions": "",
    "gate_biome_command": "",
    "biome_autofix": "",
    "biome_autofix_legalize_outside": "",
    "gate_biome_fix_command": "",
    "gates_skip_typescript": "",
    "gate_typescript_mode": "",
    "typescript_targets": "",
    "gate_typescript_base_tsconfig": "",
    "gate_typescript_extensions": "",
    "gate_typescript_command": "",
    "apply_failure_partial_gates_policy": "",
    "apply_failure_zero_gates_policy": "",
    "gate_ruff_mode": "",
    "gate_mypy_mode": "",
    "gate_pytest_mode": "",
    "pytest_routing_mode": "",
    "pytest_roots": "pytest_roots",
    "pytest_tree": "pytest_tree",
    "pytest_namespace_modules": "pytest_namespace_modules",
    "pytest_dependencies": "pytest_dependencies",
    "pytest_external_dependencies": "pytest_external_dependencies",
    "pytest_full_suite_prefixes": "",
    "gate_docs_include": "",
    "gate_docs_exclude": "",
    "gate_docs_required_files": "",
    "gates_order": "",
    "gate_badguys_runner": "",
    "gate_badguys_command": "",
    "gate_badguys_cwd": "",
    "ruff_targets": "",
    "pytest_targets": "",
    "mypy_targets": "",
    "gate_pytest_py_prefixes": "",
    "gate_pytest_js_prefixes": "",
    "pytest_use_venv": "",
    "fail_if_live_files_changed": "",
    "live_changed_resolution": "",
    "commit_and_push": "",
    "post_success_audit": "",
    "no_rollback": "",
    "rollback_workspace_on_fail": "",
    "live_repo_guard": "",
    "live_repo_guard_scope": "",
    "audit_rubric_guard": "",
    "patch_jail": "",
    "patch_jail_unshare_net": "",
    "skip_up_to_date": "",
    "allow_non_main": "",
    "allow_push_fail": "",
    "declared_untouched_fail": "",
    "allow_declared_untouched": "",
    "allow_outside_files": "",
    "patch_dir_name": "",
    "patch_layout_logs_dir": "",
    "patch_layout_json_dir": "",
    "patch_layout_workspaces_dir": "",
    "patch_layout_successful_dir": "",
    "patch_layout_unsuccessful_dir": "",
    "lockfile_name": "",
    "current_log_symlink_name": "",
    "current_log_symlink_enabled": "",
    "log_ts_format": "",
    "log_template_issue": "",
    "log_template_finalize": "",
    "failure_zip_name": "",
    "failure_zip_template": "",
    "failure_zip_cleanup_glob_template": "",
    "failure_zip_keep_per_issue": "",
    "failure_zip_delete_on_success_commit": "",
    "failure_zip_log_dir": "",
    "failure_zip_patch_dir": "",
    "workspace_issue_dir_template": "",
    "workspace_repo_dir_name": "",
    "workspace_meta_filename": "",
    "workspace_history_logs_dir": "",
    "workspace_history_oldlogs_dir": "",
    "workspace_history_patches_dir": "",
    "workspace_history_oldpatches_dir": "",
    "blessed_gate_outputs": "",
    "scope_ignore_prefixes": "",
    "scope_ignore_suffixes": "",
    "scope_ignore_contains": "",
    "venv_bootstrap_mode": "",
    "venv_bootstrap_python": "",
    "default_branch": "",
    "success_archive_name": "",
    "success_archive_dir": "",
    "success_archive_cleanup_glob_template": "",
    "success_archive_keep_count": "",
    "require_up_to_date": "",
    "enforce_main_branch": "",
    "update_workspace": "",
    "soft_reset_workspace": "",
    "test_mode": "",
    "test_mode_isolate_patch_dir": "",
    "delete_workspace_on_success": "",
    "ascii_only_patch": "",
    "gate_monolith_enabled": "",
    "gate_monolith_mode": "",
    "gate_monolith_scan_scope": "",
    "gate_monolith_extensions": "",
    "gate_monolith_compute_fanin": "",
    "gate_monolith_on_parse_error": "",
    "gate_monolith_areas_prefixes": "",
    "gate_monolith_areas_names": "",
    "gate_monolith_areas_dynamic": "",
    "gate_monolith_large_loc": "",
    "gate_monolith_huge_loc": "",
    "gate_monolith_large_allow_loc_increase": "",
    "gate_monolith_huge_allow_loc_increase": "",
    "gate_monolith_large_allow_exports_delta": "",
    "gate_monolith_huge_allow_exports_delta": "",
    "gate_monolith_large_allow_imports_delta": "",
    "gate_monolith_huge_allow_imports_delta": "",
    "gate_monolith_new_file_max_loc": "",
    "gate_monolith_new_file_max_exports": "",
    "gate_monolith_new_file_max_imports": "",
    "gate_monolith_hub_fanin_delta": "",
    "gate_monolith_hub_fanout_delta": "",
    "gate_monolith_hub_exports_delta_min": "",
    "gate_monolith_hub_loc_delta_min": "",
    "gate_monolith_crossarea_min_distinct_areas": "",
    "gate_monolith_catchall_basenames": "",
    "gate_monolith_catchall_dirs": "",
    "gate_monolith_catchall_allowlist": "",
}


_LABEL_BY_KEY: dict[str, str] = {
    "gates_allow_fail": "Gates: allow fail",
    "gates_order": "Gates: order",
    "gates_skip_mypy": "Gates: skip mypy",
    "gates_skip_pytest": "Gates: skip pytest",
    "gates_skip_ruff": "Gates: skip ruff",
    "mypy_targets": "Mypy: targets",
    "pytest_targets": "Pytest: targets",
    "gate_pytest_py_prefixes": "Pytest: Python trigger prefixes",
    "pytest_routing_mode": "Pytest: routing mode",
    "pytest_roots": "Pytest: namespace roots",
    "pytest_tree": "Pytest: namespace tree",
    "pytest_namespace_modules": "Pytest: namespace modules",
    "pytest_dependencies": "Pytest: namespace dependencies",
    "pytest_external_dependencies": "Pytest: external dependencies",
    "pytest_full_suite_prefixes": "Pytest: full-suite prefixes",
    "pytest_use_venv": "Pytest: use venv",
    "run_all_tests": "Workflow: run all gates",
    "allow_non_main": "Git safety: allow non-main",
    "enforce_main_branch": "Git safety: enforce main branch",
    "require_up_to_date": "Git safety: require up-to-date",
    "skip_up_to_date": "Git safety: skip up-to-date",
    "audit_rubric_guard": "Audit: rubric guard",
    "default_branch": "Git: default branch",
    "live_repo_guard": "Git safety: live repo guard",
    "live_repo_guard_scope": "Git safety: live repo guard scope",
    "repo_root": "Paths: repo root",
    "artifacts_root": "Paths: artifacts root",
    "target_repo_name": "Target selection: target repo name",
    "target_repo_roots": "Paths: target repo roots",
    "active_target_repo_root": "Paths: active target repo root",
    "runner_subprocess_timeout_s": "Runner: subprocess timeout (s)",
    "ruff_autofix": "Ruff: autofix",
    "ruff_autofix_legalize_outside": "Ruff: autofix legalize outside",
    "ruff_format": "Ruff: format",
    "biome_format": "Biome: format",
    "biome_format_legalize_outside": "Biome: format legalize outside",
    "gate_biome_format_command": "Biome: format command",
    "biome_autofix": "Biome: autofix",
    "biome_autofix_legalize_outside": "Biome: autofix legalize outside",
    "gate_biome_fix_command": "Biome: fix command",
    "ascii_only_patch": "Patch format: ASCII only",
    "unified_patch": "Patch format: unified patch",
    "unified_patch_continue": "Patch format: unified patch continue",
    "unified_patch_strip": "Patch format: unified patch strip",
    "unified_patch_touch_on_fail": "Patch format: unified patch touch on fail",
    "patch_jail": "Sandbox: patch jail",
    "patch_jail_unshare_net": "Sandbox: unshare net",
    "allow_declared_untouched": "Scope: allow declared untouched",
    "allow_no_op": "Scope: allow no-op",
    "allow_outside_files": "Scope: allow outside files",
    "allow_push_fail": "Promotion: allow push fail",
    "declared_untouched_fail": "Scope: declared untouched fail",
    "enforce_allowed_files": "Scope: enforce allowed files",
    "no_op_fail": "Scope: no-op fail",
    "no_rollback": "Commit/push: disable rollback",
    "post_success_audit": "Workflow: post-success audit",
    "soft_reset_workspace": "Workflow: soft reset workspace",
    "test_mode": "Workflow: test mode",
    "test_mode_isolate_patch_dir": "Workflow: isolate patch dir in test mode",
    "update_workspace": "Workflow: update workspace",
}


_HELP_BY_KEY: dict[str, str] = {
    "gates_allow_fail": (
        "Allow gates to fail without failing the overall run. "
        "See: scripts/am_patch_policy_glossary.md## Key: gates_allow_fail"
    ),
    "gates_order": (
        "Ordered list of gate names to run. "
        "See: scripts/am_patch_policy_glossary.md## Key: gates_order"
    ),
    "gates_skip_mypy": (
        "Skip the mypy gate. See: scripts/am_patch_policy_glossary.md## Key: gates_skip_mypy"
    ),
    "gates_skip_pytest": (
        "Skip the pytest gate. See: scripts/am_patch_policy_glossary.md## Key: gates_skip_pytest"
    ),
    "gates_skip_ruff": (
        "Skip the ruff gate. See: scripts/am_patch_policy_glossary.md## Key: gates_skip_ruff"
    ),
    "biome_autofix": (
        "Run biome in autofix mode when the initial check fails. "
        "See: scripts/am_patch_policy_glossary.md## Key: biome_autofix"
    ),
    "biome_format": (
        "Run biome format before biome check. "
        "See: scripts/am_patch_policy_glossary.md## Key: biome_format"
    ),
    "biome_autofix_legalize_outside": (
        "Allow biome autofix to modify files outside the declared patch set. "
        "See: scripts/am_patch_policy_glossary.md## Key: biome_autofix_legalize_outside"
    ),
    "biome_format_legalize_outside": (
        "Allow biome format to modify files outside the declared patch set. "
        "See: scripts/am_patch_policy_glossary.md## Key: biome_format_legalize_outside"
    ),
    "gate_biome_format_command": (
        "Command used for biome format gate. "
        "See: scripts/am_patch_policy_glossary.md## Key: gate_biome_format_command"
    ),
    "mypy_targets": (
        "Targets passed to mypy. See: scripts/am_patch_policy_glossary.md## Key: mypy_targets"
    ),
    "pytest_targets": (
        "Targets passed to pytest. See: scripts/am_patch_policy_glossary.md## Key: pytest_targets"
    ),
    "gate_pytest_py_prefixes": (
        "Python trigger prefixes for gate_pytest_mode=auto. "
        "See: scripts/am_patch_policy_glossary.md## Key: gate_pytest_py_prefixes"
    ),
    "pytest_routing_mode": (
        "Select legacy or bucketed pytest target routing. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_routing_mode"
    ),
    "pytest_roots": (
        "Namespace root mapping for bucketed pytest routing. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_roots"
    ),
    "pytest_tree": (
        "Most-specific namespace subtree mapping for bucketed pytest routing. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_tree"
    ),
    "pytest_namespace_modules": (
        "Namespace-to-module-prefix mapping used by discovery and validator evidence. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_namespace_modules"
    ),
    "pytest_dependencies": (
        "One-way repo-verifiable namespace dependency map used for reverse-closure routing. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_dependencies"
    ),
    "pytest_external_dependencies": (
        "One-way explicit routing overrides that are not claimed as repo-verifiable evidence. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_external_dependencies"
    ),
    "pytest_full_suite_prefixes": (
        "Prefixes that escalate bucketed pytest routing to the full pytest target set. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_full_suite_prefixes"
    ),
    "pytest_use_venv": (
        "Run pytest under the configured venv python. "
        "See: scripts/am_patch_policy_glossary.md## Key: pytest_use_venv"
    ),
    "run_all_tests": (
        "Run the configured gate sequence after applying the patch. "
        "See: scripts/am_patch_policy_glossary.md## Key: run_all_tests"
    ),
    "allow_non_main": (
        "Allow running from a non-default branch. "
        "See: scripts/am_patch_policy_glossary.md## Key: allow_non_main"
    ),
    "enforce_main_branch": (
        "Require being on default_branch before running. "
        "See: scripts/am_patch_policy_glossary.md## Key: enforce_main_branch"
    ),
    "require_up_to_date": (
        "Require the local branch to be up-to-date with its upstream. "
        "See: scripts/am_patch_policy_glossary.md## Key: require_up_to_date"
    ),
    "skip_up_to_date": (
        "Skip the up-to-date check. See: scripts/am_patch_policy_glossary.md## Key: skip_up_to_date"
    ),
    "audit_rubric_guard": (
        "Require audit rubric file(s) to be present and unchanged. "
        "See: scripts/am_patch_policy_glossary.md## Key: audit_rubric_guard"
    ),
    "default_branch": (
        "Default branch name used for safety checks. "
        "See: scripts/am_patch_policy_glossary.md## Key: default_branch"
    ),
    "live_repo_guard": (
        "Protect the live repository from unexpected modifications. "
        "See: scripts/am_patch_policy_glossary.md## Key: live_repo_guard"
    ),
    "live_repo_guard_scope": (
        "Scope controlling how the live repo guard is applied. "
        "See: scripts/am_patch_policy_glossary.md## Key: live_repo_guard_scope"
    ),
    "repo_root": (
        "Optional legacy override for the active target repository root path. "
        "See: scripts/am_patch_policy_glossary.md## Key: repo_root"
    ),
    "artifacts_root": (
        "Optional override for the runner-owned artifacts root path. "
        "See: scripts/am_patch_policy_glossary.md## Key: artifacts_root"
    ),
    "target_repo_name": (
        "ASCII-only bare repo token selector for the /home/pi/<name> target family. "
        "Default: audiomason2. Failure zip target.txt is derived from the selected root."
    ),
    "target_repo_roots": (
        "Optional registry of allowed target repository roots. "
        "Dedicated CLI and --override replace the whole list value. "
        "See: scripts/am_patch_policy_glossary.md## Key: target_repo_roots"
    ),
    "active_target_repo_root": (
        "Optional explicit target repository root path selector. "
        "See: scripts/am_patch_policy_glossary.md## Key: active_target_repo_root"
    ),
    "runner_subprocess_timeout_s": (
        "Hard timeout for runner subprocesses in seconds; 0 disables it. "
        "See: scripts/am_patch_policy_glossary.md## Key: runner_subprocess_timeout_s"
    ),
    "ruff_autofix": (
        "Run ruff in autofix mode before other gates. "
        "See: scripts/am_patch_policy_glossary.md## Key: ruff_autofix"
    ),
    "ruff_autofix_legalize_outside": (
        "Allow ruff autofix to modify files outside the declared patch set. "
        "See: scripts/am_patch_policy_glossary.md## Key: ruff_autofix_legalize_outside"
    ),
    "ruff_format": (
        "Run ruff format as part of the ruff workflow. "
        "See: scripts/am_patch_policy_glossary.md## Key: ruff_format"
    ),
    "ascii_only_patch": (
        "Enforce ASCII-only content in patches and related metadata. "
        "See: scripts/am_patch_policy_glossary.md## Key: ascii_only_patch"
    ),
    "unified_patch": (
        "Apply patches in unified mode. "
        "See: scripts/am_patch_policy_glossary.md## Key: unified_patch"
    ),
    "unified_patch_continue": (
        "Continue after unified patch step. "
        "See: scripts/am_patch_policy_glossary.md## Key: unified_patch_continue"
    ),
    "unified_patch_strip": (
        "Optional strip override for patch application. "
        "See: scripts/am_patch_policy_glossary.md## Key: unified_patch_strip"
    ),
    "unified_patch_touch_on_fail": (
        "Touch patch markers when unified patch apply fails. "
        "See: scripts/am_patch_policy_glossary.md## Key: unified_patch_touch_on_fail"
    ),
    "patch_jail": (
        "Run patch application inside an isolation boundary. "
        "See: scripts/am_patch_policy_glossary.md## Key: patch_jail"
    ),
    "patch_jail_unshare_net": (
        "Disable network access inside the patch jail. "
        "See: scripts/am_patch_policy_glossary.md## Key: patch_jail_unshare_net"
    ),
    "allow_declared_untouched": (
        "Allow declaring files as untouched even if changed. "
        "See: scripts/am_patch_policy_glossary.md## Key: allow_declared_untouched"
    ),
    "allow_no_op": (
        "Allow patches that result in no changes being applied. "
        "See: scripts/am_patch_policy_glossary.md## Key: allow_no_op"
    ),
    "allow_outside_files": (
        "Allow modifying files outside the declared set. "
        "See: scripts/am_patch_policy_glossary.md## Key: allow_outside_files"
    ),
    "allow_push_fail": (
        "Do not fail the run if git push fails after a commit. "
        "See: scripts/am_patch_policy_glossary.md## Key: allow_push_fail"
    ),
    "declared_untouched_fail": (
        "Fail when declared-untouched files are detected as changed. "
        "See: scripts/am_patch_policy_glossary.md## Key: declared_untouched_fail"
    ),
    "enforce_allowed_files": (
        "Enforce the allowed-files list during patch application. "
        "See: scripts/am_patch_policy_glossary.md## Key: enforce_allowed_files"
    ),
    "no_op_fail": (
        "Fail when the patch applies as a no-op. "
        "See: scripts/am_patch_policy_glossary.md## Key: no_op_fail"
    ),
    "no_rollback": (
        "Disable rollback on commit/push failure. "
        "See: scripts/am_patch_policy_glossary.md## Key: no_rollback"
    ),
    "post_success_audit": (
        "Run post-success audit checks after gates succeed. "
        "See: scripts/am_patch_policy_glossary.md## Key: post_success_audit"
    ),
    "soft_reset_workspace": (
        "Perform a soft reset of the workspace before applying the patch. "
        "See: scripts/am_patch_policy_glossary.md## Key: soft_reset_workspace"
    ),
    "test_mode": (
        "Run the runner in a test-oriented mode. "
        "See: scripts/am_patch_policy_glossary.md## Key: test_mode"
    ),
    "test_mode_isolate_patch_dir": (
        "Isolate patch_dir during test_mode. "
        "See: scripts/am_patch_policy_glossary.md## Key: test_mode_isolate_patch_dir"
    ),
    "update_workspace": (
        "Update the workspace repository before running. "
        "See: scripts/am_patch_policy_glossary.md## Key: update_workspace"
    ),
}


# Explicit schema type overrides for fields that are not editable via PatchHub.
_READ_ONLY_TYPE_BY_KEY: dict[str, str] = {}


# Explicit enum allow-lists for enum-like Policy fields.
_ENUM_BY_KEY: dict[str, list[str]] = {
    "verbosity": ["debug", "verbose", "normal", "quiet"],
    "log_level": ["quiet", "normal", "warning", "verbose", "debug"],
    "console_color": ["auto", "always", "never"],
    "ipc_socket_mode": ["patch_dir", "base_dir", "system_runtime"],
    "ipc_socket_on_startup_exists": ["fail", "wait_then_fail", "unlink_if_stale"],
    "venv_bootstrap_mode": ["auto", "always", "never"],
    "success_archive_dir": ["patch_dir", "successful_dir"],
    "gate_monolith_mode": ["strict", "warn_only", "report_only"],
    "gate_monolith_scan_scope": ["patch", "workspace"],
    "gate_monolith_on_parse_error": ["fail", "warn"],
    "live_changed_resolution": ["fail", "overwrite_live", "overwrite_workspace"],
    "apply_failure_partial_gates_policy": ["never", "always", "repair_only"],
    "apply_failure_zero_gates_policy": ["never", "always", "repair_only"],
    "gate_ruff_mode": ["auto", "always"],
    "gate_mypy_mode": ["auto", "always"],
    "gate_pytest_mode": ["auto", "always"],
    "pytest_routing_mode": ["legacy", "bucketed"],
    "gate_typescript_mode": ["auto", "always"],
}


def _infer_schema_type(typ: Any) -> str:
    origin = get_origin(typ)
    args = get_args(typ)

    if typ is bool:
        return "bool"
    if typ is int:
        return "int"
    if typ is str:
        return "str"

    if origin is list and args and args[0] is str:
        return "list[str]"
    if origin is dict and len(args) == 2 and args[0] is str:
        value = args[1]
        if get_origin(value) is list and get_args(value) and get_args(value)[0] is str:
            return "dict[str,list[str]]"
        if value is str:
            return "dict[str,str]"

    # PEP 604 union (e.g., str | None)
    if args and len(args) == 2 and type(None) in args:
        other = args[0] if args[1] is type(None) else args[1]
        if other is str:
            return "optional[str]"
        if other is int:
            return "int"
        if other is bool:
            return "bool"
        if get_origin(other) is list and get_args(other) and get_args(other)[0] is str:
            return "list[str]"

    # Fallback: treat as string surface (read-only paths, complex collections, etc.).
    return "str"


def _get_default_value(field_obj: Field[Any], defaults: Policy) -> Any:
    v = getattr(defaults, field_obj.name)
    return v


def get_policy_schema() -> dict[str, Any]:
    defaults = Policy()
    # Policy uses `from __future__ import annotations`, so Field.type may contain
    # strings. Resolve annotations so type inference is correct.
    hints = get_type_hints(Policy)
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy": {},
    }

    for f in fields(Policy):
        if f.name == "_src":
            continue

        if f.name not in _SECTION_BY_KEY:
            raise RuntimeError(f"Missing section mapping for policy key: {f.name}")

        type_name = _infer_schema_type(hints.get(f.name, f.type))
        read_only = False
        if f.name in _READ_ONLY_TYPE_BY_KEY:
            type_name = _READ_ONLY_TYPE_BY_KEY[f.name]
            read_only = True

        item: dict[str, Any] = {
            "key": f.name,
            "type": type_name,
            "section": _SECTION_BY_KEY[f.name],
            "default": _get_default_value(f, defaults),
            "label": _LABEL_BY_KEY.get(f.name, f.name),
            "help": _HELP_BY_KEY.get(f.name, ""),
        }
        if f.name in _ENUM_BY_KEY:
            item["enum"] = list(_ENUM_BY_KEY[f.name])
        if read_only:
            item["read_only"] = True

        out["policy"][f.name] = item

    return out
