from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Any

from .config_ipc_surface import IPC_NONNEGATIVE_IPC_INT_KEYS
from .config_monolith_areas import parse_monolith_areas
from .errors import RunnerError
from .policy_gate_modes import apply_gate_modes

ConfigBool = Callable[[dict[str, Any], str, bool], bool]
ConfigStrRequired = Callable[[dict[str, Any], str, str], str]
ConfigListStr = Callable[[dict[str, Any], str, list[str]], list[str]]
ConfigDictListStr = Callable[
    [dict[str, Any], str, dict[str, list[str]]],
    dict[str, list[str]],
]
MarkCfg = Callable[[Any, dict[str, Any], str], None]


def apply_gate_execution_cfg(
    cfg: dict[str, Any],
    p: Any,
    *,
    as_bool: ConfigBool,
    as_str_required: ConfigStrRequired,
    as_list_str: ConfigListStr,
    as_dict_list_str: ConfigDictListStr,
    mark_cfg: MarkCfg,
) -> None:
    p.run_all_tests = as_bool(cfg, "run_all_tests", p.run_all_tests)
    mark_cfg(p, cfg, "run_all_tests")
    p.compile_check = as_bool(cfg, "compile_check", p.compile_check)
    mark_cfg(p, cfg, "compile_check")
    p.ruff_autofix = as_bool(cfg, "ruff_autofix", p.ruff_autofix)
    mark_cfg(p, cfg, "ruff_autofix")
    p.ruff_autofix_legalize_outside = as_bool(
        cfg, "ruff_autofix_legalize_outside", p.ruff_autofix_legalize_outside
    )
    mark_cfg(p, cfg, "ruff_autofix_legalize_outside")
    p.ruff_format = as_bool(cfg, "ruff_format", p.ruff_format)
    mark_cfg(p, cfg, "ruff_format")

    p.gates_allow_fail = as_bool(cfg, "gates_allow_fail", p.gates_allow_fail)
    mark_cfg(p, cfg, "gates_allow_fail")
    p.apply_failure_partial_gates_policy = as_str_required(
        cfg, "apply_failure_partial_gates_policy", p.apply_failure_partial_gates_policy
    )
    mark_cfg(p, cfg, "apply_failure_partial_gates_policy")
    p.apply_failure_zero_gates_policy = as_str_required(
        cfg, "apply_failure_zero_gates_policy", p.apply_failure_zero_gates_policy
    )
    mark_cfg(p, cfg, "apply_failure_zero_gates_policy")

    p.gates_skip_dont_touch = as_bool(cfg, "gates_skip_dont_touch", p.gates_skip_dont_touch)
    mark_cfg(p, cfg, "gates_skip_dont_touch")
    p.dont_touch_paths = as_list_str(cfg, "dont_touch_paths", p.dont_touch_paths)
    mark_cfg(p, cfg, "dont_touch_paths")

    p.gates_skip_ruff = as_bool(cfg, "gates_skip_ruff", p.gates_skip_ruff)
    mark_cfg(p, cfg, "gates_skip_ruff")
    p.gates_skip_pytest = as_bool(cfg, "gates_skip_pytest", p.gates_skip_pytest)
    mark_cfg(p, cfg, "gates_skip_pytest")
    p.gates_skip_mypy = as_bool(cfg, "gates_skip_mypy", p.gates_skip_mypy)
    mark_cfg(p, cfg, "gates_skip_mypy")
    p.gates_skip_docs = as_bool(cfg, "gates_skip_docs", p.gates_skip_docs)
    mark_cfg(p, cfg, "gates_skip_docs")

    p.gates_skip_monolith = as_bool(cfg, "gates_skip_monolith", p.gates_skip_monolith)
    mark_cfg(p, cfg, "gates_skip_monolith")
    p.gate_monolith_enabled = as_bool(cfg, "gate_monolith_enabled", p.gate_monolith_enabled)
    mark_cfg(p, cfg, "gate_monolith_enabled")

    p.gate_monolith_mode = str(cfg.get("gate_monolith_mode", p.gate_monolith_mode)).strip()
    mark_cfg(p, cfg, "gate_monolith_mode")
    if p.gate_monolith_mode not in ("strict", "warn_only", "report_only"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            (
                "invalid gate_monolith_mode="
                f"{p.gate_monolith_mode!r}; allowed: strict|warn_only|report_only"
            ),
        )

    p.gate_monolith_scan_scope = str(
        cfg.get("gate_monolith_scan_scope", p.gate_monolith_scan_scope)
    ).strip()
    mark_cfg(p, cfg, "gate_monolith_scan_scope")
    if p.gate_monolith_scan_scope not in ("patch", "workspace"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            (
                "invalid gate_monolith_scan_scope="
                f"{p.gate_monolith_scan_scope!r}; allowed: patch|workspace"
            ),
        )

    if "gate_monolith_extensions" in cfg:
        raw_ext = cfg["gate_monolith_extensions"]
        if not isinstance(raw_ext, list) or not all(isinstance(x, str) for x in raw_ext):
            raise RunnerError(
                "CONFIG",
                "INVALID",
                "gate_monolith_extensions must be list[str]",
            )
        cleaned: list[str] = []
        for item in raw_ext:
            s = str(item).strip()
            if not s:
                continue
            if not s.startswith("."):
                s = "." + s
            if s not in cleaned:
                cleaned.append(s)
        if not cleaned:
            raise RunnerError(
                "CONFIG",
                "INVALID",
                "gate_monolith_extensions must be non-empty",
            )
        p.gate_monolith_extensions = cleaned
        mark_cfg(p, cfg, "gate_monolith_extensions")

    p.gate_monolith_compute_fanin = as_bool(
        cfg, "gate_monolith_compute_fanin", p.gate_monolith_compute_fanin
    )
    mark_cfg(p, cfg, "gate_monolith_compute_fanin")

    p.gate_monolith_on_parse_error = str(
        cfg.get("gate_monolith_on_parse_error", p.gate_monolith_on_parse_error)
    ).strip()
    mark_cfg(p, cfg, "gate_monolith_on_parse_error")
    if p.gate_monolith_on_parse_error not in ("fail", "warn"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            (
                "invalid gate_monolith_on_parse_error="
                f"{p.gate_monolith_on_parse_error!r}; allowed: fail|warn"
            ),
        )

    prefixes, names, dynamic = parse_monolith_areas(cfg)
    p.gate_monolith_areas_prefixes = prefixes
    mark_cfg(p, cfg, "gate_monolith_areas_prefixes")
    p.gate_monolith_areas_names = names
    mark_cfg(p, cfg, "gate_monolith_areas_names")
    p.gate_monolith_areas_dynamic = dynamic
    mark_cfg(p, cfg, "gate_monolith_areas_dynamic")

    for k in (
        "gate_monolith_large_loc",
        "gate_monolith_huge_loc",
        "gate_monolith_large_allow_loc_increase",
        "gate_monolith_huge_allow_loc_increase",
        "gate_monolith_large_allow_exports_delta",
        "gate_monolith_huge_allow_exports_delta",
        "gate_monolith_large_allow_imports_delta",
        "gate_monolith_huge_allow_imports_delta",
        "gate_monolith_new_file_max_loc",
        "gate_monolith_new_file_max_exports",
        "gate_monolith_new_file_max_imports",
        "gate_monolith_hub_fanin_delta",
        "gate_monolith_hub_fanout_delta",
        "gate_monolith_hub_exports_delta_min",
        "gate_monolith_hub_loc_delta_min",
        "gate_monolith_crossarea_min_distinct_areas",
        *IPC_NONNEGATIVE_IPC_INT_KEYS,
    ):
        if k in cfg:
            setattr(p, k, int(cfg[k]))
            mark_cfg(p, cfg, k)
        if int(getattr(p, k)) < 0:
            raise RunnerError("CONFIG", "INVALID", f"{k} must be >= 0")

    if p.ipc_handshake_enabled and p.ipc_handshake_wait_s < 1:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "ipc_handshake_wait_s must be >= 1 when ipc_handshake_enabled=true",
        )

    p.gate_monolith_catchall_basenames = as_list_str(
        cfg, "gate_monolith_catchall_basenames", p.gate_monolith_catchall_basenames
    )
    mark_cfg(p, cfg, "gate_monolith_catchall_basenames")
    p.gate_monolith_catchall_dirs = as_list_str(
        cfg, "gate_monolith_catchall_dirs", p.gate_monolith_catchall_dirs
    )
    mark_cfg(p, cfg, "gate_monolith_catchall_dirs")
    p.gate_monolith_catchall_allowlist = as_list_str(
        cfg, "gate_monolith_catchall_allowlist", p.gate_monolith_catchall_allowlist
    )
    mark_cfg(p, cfg, "gate_monolith_catchall_allowlist")

    p.gates_skip_js = as_bool(cfg, "gates_skip_js", p.gates_skip_js)
    mark_cfg(p, cfg, "gates_skip_js")
    p.gate_js_extensions = as_list_str(cfg, "gate_js_extensions", p.gate_js_extensions)
    mark_cfg(p, cfg, "gate_js_extensions")

    if "gate_js_command" in cfg:
        raw_cmd = cfg["gate_js_command"]
        if isinstance(raw_cmd, str):
            cmd_list = shlex.split(raw_cmd)
        elif isinstance(raw_cmd, list) and all(isinstance(x, str) for x in raw_cmd):
            cmd_list = raw_cmd
        else:
            raise RunnerError("CONFIG", "INVALID", "gate_js_command must be a string or list[str]")
        if not cmd_list:
            raise RunnerError("CONFIG", "INVALID", "gate_js_command must be non-empty")
        p.gate_js_command = cmd_list
        mark_cfg(p, cfg, "gate_js_command")

    p.gates_skip_biome = as_bool(cfg, "gates_skip_biome", p.gates_skip_biome)
    mark_cfg(p, cfg, "gates_skip_biome")
    p.gate_biome_extensions = as_list_str(cfg, "gate_biome_extensions", p.gate_biome_extensions)
    mark_cfg(p, cfg, "gate_biome_extensions")

    p.biome_autofix = as_bool(cfg, "biome_autofix", p.biome_autofix)
    mark_cfg(p, cfg, "biome_autofix")
    p.biome_autofix_legalize_outside = as_bool(
        cfg, "biome_autofix_legalize_outside", p.biome_autofix_legalize_outside
    )
    mark_cfg(p, cfg, "biome_autofix_legalize_outside")
    p.biome_format = as_bool(cfg, "biome_format", p.biome_format)
    mark_cfg(p, cfg, "biome_format")
    p.biome_format_legalize_outside = as_bool(
        cfg, "biome_format_legalize_outside", p.biome_format_legalize_outside
    )
    mark_cfg(p, cfg, "biome_format_legalize_outside")

    for k in ("gate_biome_command", "gate_biome_fix_command", "gate_biome_format_command"):
        if k not in cfg:
            continue
        raw_cmd = cfg[k]
        if isinstance(raw_cmd, str):
            cmd_list = shlex.split(raw_cmd)
        elif isinstance(raw_cmd, list) and all(isinstance(x, str) for x in raw_cmd):
            cmd_list = raw_cmd
        else:
            raise RunnerError("CONFIG", "INVALID", f"{k} must be a string or list[str]")
        cmd_list0 = [str(x).strip() for x in cmd_list if str(x).strip()]
        if not cmd_list0:
            raise RunnerError("CONFIG", "INVALID", f"{k} must be non-empty")
        setattr(p, k, cmd_list0)
        mark_cfg(p, cfg, k)

    p.gates_skip_typescript = as_bool(cfg, "gates_skip_typescript", p.gates_skip_typescript)
    mark_cfg(p, cfg, "gates_skip_typescript")
    p.gate_typescript_extensions = as_list_str(
        cfg, "gate_typescript_extensions", p.gate_typescript_extensions
    )
    mark_cfg(p, cfg, "gate_typescript_extensions")

    if "gate_typescript_command" in cfg:
        raw_cmd = cfg["gate_typescript_command"]
        if isinstance(raw_cmd, str):
            cmd_list = shlex.split(raw_cmd)
        elif isinstance(raw_cmd, list) and all(isinstance(x, str) for x in raw_cmd):
            cmd_list = raw_cmd
        else:
            raise RunnerError(
                "CONFIG",
                "INVALID",
                "gate_typescript_command must be a string or list[str]",
            )
        if not cmd_list:
            raise RunnerError("CONFIG", "INVALID", "gate_typescript_command must be non-empty")
        p.gate_typescript_command = cmd_list
        mark_cfg(p, cfg, "gate_typescript_command")

    p.gate_docs_include = as_list_str(cfg, "gate_docs_include", p.gate_docs_include)
    mark_cfg(p, cfg, "gate_docs_include")
    p.gate_docs_exclude = as_list_str(cfg, "gate_docs_exclude", p.gate_docs_exclude)
    mark_cfg(p, cfg, "gate_docs_exclude")
    p.gate_docs_required_files = as_list_str(
        cfg, "gate_docs_required_files", p.gate_docs_required_files
    )
    mark_cfg(p, cfg, "gate_docs_required_files")

    p.gates_order = as_list_str(cfg, "gates_order", p.gates_order)
    mark_cfg(p, cfg, "gates_order")

    p.gate_badguys_runner = str(cfg.get("gate_badguys_runner", p.gate_badguys_runner))
    mark_cfg(p, cfg, "gate_badguys_runner")
    if p.gate_badguys_runner not in ("auto", "on", "off"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"invalid gate_badguys_runner={p.gate_badguys_runner!r}; allowed: auto|on|off",
        )

    if "gate_badguys_command" in cfg:
        raw_cmd = cfg["gate_badguys_command"]
        if isinstance(raw_cmd, str):
            cmd_list = shlex.split(raw_cmd)
        elif isinstance(raw_cmd, list) and all(isinstance(x, str) for x in raw_cmd):
            cmd_list = raw_cmd
        else:
            raise RunnerError(
                "CONFIG",
                "INVALID",
                "gate_badguys_command must be a string or list[str]",
            )
        if not cmd_list:
            raise RunnerError("CONFIG", "INVALID", "gate_badguys_command must be non-empty")
        p.gate_badguys_command = cmd_list
        mark_cfg(p, cfg, "gate_badguys_command")

    if "gate_badguys_cwd" in cfg:
        p.gate_badguys_cwd = str(cfg["gate_badguys_cwd"]).strip().lower()
        mark_cfg(p, cfg, "gate_badguys_cwd")
        if p.gate_badguys_cwd not in ("auto", "workspace", "clone", "live"):
            raise RunnerError(
                "CONFIG",
                "INVALID",
                (
                    f"invalid gate_badguys_cwd={p.gate_badguys_cwd!r}; allowed: "
                    "auto|workspace|clone|live"
                ),
            )

    p.compile_targets = as_list_str(cfg, "compile_targets", p.compile_targets)
    mark_cfg(p, cfg, "compile_targets")
    p.compile_exclude = as_list_str(cfg, "compile_exclude", p.compile_exclude)
    mark_cfg(p, cfg, "compile_exclude")
    p.ruff_targets = as_list_str(cfg, "ruff_targets", p.ruff_targets)
    mark_cfg(p, cfg, "ruff_targets")
    p.pytest_targets = as_list_str(cfg, "pytest_targets", p.pytest_targets)
    mark_cfg(p, cfg, "pytest_targets")
    p.pytest_routing_mode = str(cfg.get("pytest_routing_mode", p.pytest_routing_mode)).strip()
    mark_cfg(p, cfg, "pytest_routing_mode")
    if p.pytest_routing_mode not in ("legacy", "bucketed"):
        raise RunnerError(
            "CONFIG",
            "INVALID_PYTEST_ROUTING_MODE",
            f"invalid pytest_routing_mode: {p.pytest_routing_mode!r}",
        )
    if "pytest_roots" in cfg:
        raw_roots = cfg["pytest_roots"]
        if not isinstance(raw_roots, dict):
            raise RunnerError("CONFIG", "INVALID", "pytest_roots must be dict[str,str]")
        p.pytest_roots = {
            str(key).strip(): str(value).strip()
            for key, value in raw_roots.items()
            if str(key).strip() and str(value).strip()
        }
        mark_cfg(p, cfg, "pytest_roots")

    if "pytest_tree" in cfg:
        raw_tree = cfg["pytest_tree"]
        if not isinstance(raw_tree, dict):
            raise RunnerError("CONFIG", "INVALID", "pytest_tree must be dict[str,str]")
        p.pytest_tree = {
            str(key).strip(): str(value).strip()
            for key, value in raw_tree.items()
            if str(key).strip() and str(value).strip()
        }
        mark_cfg(p, cfg, "pytest_tree")

    p.pytest_namespace_modules = as_dict_list_str(
        cfg,
        "pytest_namespace_modules",
        p.pytest_namespace_modules,
    )
    mark_cfg(p, cfg, "pytest_namespace_modules")
    p.pytest_dependencies = as_dict_list_str(
        cfg,
        "pytest_dependencies",
        p.pytest_dependencies,
    )
    mark_cfg(p, cfg, "pytest_dependencies")
    p.pytest_external_dependencies = as_dict_list_str(
        cfg,
        "pytest_external_dependencies",
        p.pytest_external_dependencies,
    )
    mark_cfg(p, cfg, "pytest_external_dependencies")
    p.pytest_full_suite_prefixes = as_list_str(
        cfg,
        "pytest_full_suite_prefixes",
        p.pytest_full_suite_prefixes,
    )
    mark_cfg(p, cfg, "pytest_full_suite_prefixes")
    p.mypy_targets = as_list_str(cfg, "mypy_targets", p.mypy_targets)
    mark_cfg(p, cfg, "mypy_targets")
    p.typescript_targets = as_list_str(cfg, "typescript_targets", p.typescript_targets)
    mark_cfg(p, cfg, "typescript_targets")

    if "gate_typescript_base_tsconfig" in cfg:
        p.gate_typescript_base_tsconfig = str(cfg["gate_typescript_base_tsconfig"]).strip()
        mark_cfg(p, cfg, "gate_typescript_base_tsconfig")

    apply_gate_modes(cfg, p, mark_cfg)

    p.pytest_use_venv = as_bool(cfg, "pytest_use_venv", p.pytest_use_venv)
    mark_cfg(p, cfg, "pytest_use_venv")
