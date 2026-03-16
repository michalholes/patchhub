from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import gates as gates_mod
from .config import Policy
from .log import Logger
from .scope import changed_path_entries


def run_policy_gates(
    *,
    logger: Logger,
    cwd: Path,
    repo_root: Path,
    policy: Policy,
    decision_paths: list[str],
    progress: Callable[[str], None] | None,
) -> None:
    """Run gates using a single canonical Policy->run_gates wiring.

    All runner modes MUST call this entry point to avoid divergent gate wiring.
    """

    docs_status_entries = changed_path_entries(logger, cwd)

    gates_mod.run_gates(
        logger,
        cwd=cwd,
        repo_root=repo_root,
        run_all=policy.run_all_tests,
        compile_check=policy.compile_check,
        compile_targets=policy.compile_targets,
        compile_exclude=policy.compile_exclude,
        allow_fail=policy.gates_allow_fail,
        skip_dont_touch=policy.gates_skip_dont_touch,
        dont_touch_paths=policy.dont_touch_paths,
        skip_ruff=policy.gates_skip_ruff,
        skip_js=policy.gates_skip_js,
        skip_biome=policy.gates_skip_biome,
        skip_typescript=policy.gates_skip_typescript,
        skip_pytest=policy.gates_skip_pytest,
        skip_mypy=policy.gates_skip_mypy,
        skip_docs=policy.gates_skip_docs,
        skip_monolith=policy.gates_skip_monolith,
        gate_monolith_enabled=policy.gate_monolith_enabled,
        gate_monolith_mode=policy.gate_monolith_mode,
        gate_monolith_scan_scope=policy.gate_monolith_scan_scope,
        gate_monolith_extensions=policy.gate_monolith_extensions,
        gate_monolith_compute_fanin=policy.gate_monolith_compute_fanin,
        gate_monolith_on_parse_error=policy.gate_monolith_on_parse_error,
        gate_monolith_areas_prefixes=policy.gate_monolith_areas_prefixes,
        gate_monolith_areas_names=policy.gate_monolith_areas_names,
        gate_monolith_areas_dynamic=policy.gate_monolith_areas_dynamic,
        gate_monolith_large_loc=policy.gate_monolith_large_loc,
        gate_monolith_huge_loc=policy.gate_monolith_huge_loc,
        gate_monolith_large_allow_loc_increase=policy.gate_monolith_large_allow_loc_increase,
        gate_monolith_huge_allow_loc_increase=policy.gate_monolith_huge_allow_loc_increase,
        gate_monolith_large_allow_exports_delta=policy.gate_monolith_large_allow_exports_delta,
        gate_monolith_huge_allow_exports_delta=policy.gate_monolith_huge_allow_exports_delta,
        gate_monolith_large_allow_imports_delta=policy.gate_monolith_large_allow_imports_delta,
        gate_monolith_huge_allow_imports_delta=policy.gate_monolith_huge_allow_imports_delta,
        gate_monolith_new_file_max_loc=policy.gate_monolith_new_file_max_loc,
        gate_monolith_new_file_max_exports=policy.gate_monolith_new_file_max_exports,
        gate_monolith_new_file_max_imports=policy.gate_monolith_new_file_max_imports,
        gate_monolith_hub_fanin_delta=policy.gate_monolith_hub_fanin_delta,
        gate_monolith_hub_fanout_delta=policy.gate_monolith_hub_fanout_delta,
        gate_monolith_hub_exports_delta_min=policy.gate_monolith_hub_exports_delta_min,
        gate_monolith_hub_loc_delta_min=policy.gate_monolith_hub_loc_delta_min,
        gate_monolith_crossarea_min_distinct_areas=(
            policy.gate_monolith_crossarea_min_distinct_areas
        ),
        gate_monolith_catchall_basenames=policy.gate_monolith_catchall_basenames,
        gate_monolith_catchall_dirs=policy.gate_monolith_catchall_dirs,
        gate_monolith_catchall_allowlist=policy.gate_monolith_catchall_allowlist,
        docs_include=policy.gate_docs_include,
        docs_exclude=policy.gate_docs_exclude,
        docs_required_files=policy.gate_docs_required_files,
        docs_status_entries=docs_status_entries,
        js_extensions=policy.gate_js_extensions,
        js_command=policy.gate_js_command,
        biome_extensions=policy.gate_biome_extensions,
        biome_command=policy.gate_biome_command,
        biome_format=policy.biome_format,
        biome_format_command=policy.gate_biome_format_command,
        biome_autofix=policy.biome_autofix,
        biome_fix_command=policy.gate_biome_fix_command,
        typescript_extensions=policy.gate_typescript_extensions,
        typescript_command=policy.gate_typescript_command,
        gate_typescript_mode=policy.gate_typescript_mode,
        typescript_targets=policy.typescript_targets,
        gate_typescript_base_tsconfig=policy.gate_typescript_base_tsconfig,
        ruff_format=policy.ruff_format,
        ruff_autofix=policy.ruff_autofix,
        ruff_targets=policy.ruff_targets,
        pytest_targets=policy.pytest_targets,
        mypy_targets=policy.mypy_targets,
        gate_ruff_mode=policy.gate_ruff_mode,
        gate_mypy_mode=policy.gate_mypy_mode,
        gate_pytest_mode=policy.gate_pytest_mode,
        gate_pytest_py_prefixes=policy.gate_pytest_py_prefixes,
        gate_pytest_js_prefixes=policy.gate_pytest_js_prefixes,
        pytest_routing_policy={
            "pytest_routing_mode": policy.pytest_routing_mode,
            "pytest_roots": policy.pytest_roots,
            "pytest_tree": policy.pytest_tree,
            "pytest_dependencies": policy.pytest_dependencies,
            "pytest_full_suite_prefixes": policy.pytest_full_suite_prefixes,
        },
        gates_order=policy.gates_order,
        pytest_use_venv=policy.pytest_use_venv,
        decision_paths=decision_paths,
        progress=progress,
    )
