from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .config_file import _flatten_sections, load_config
from .config_gate_execution import apply_gate_execution_cfg
from .config_ipc_surface import apply_ipc_cfg_surface
from .errors import RunnerError
from .initial_self_backup import normalize_self_backup_policy
from .policy_monolith_mixin import PolicyMonolithMixin
from .pytest_namespace_config import (
    PYTEST_DEPENDENCIES_DEFAULT,
    PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    PYTEST_FULL_SUITE_PREFIXES_DEFAULT,
    PYTEST_NAMESPACE_MODULES_DEFAULT,
    PYTEST_ROOTS_DEFAULT,
    PYTEST_TREE_DEFAULT,
)
from .success_archive_retention import validate_success_archive_retention

__all__ = [
    "Policy",
    "BOOTSTRAP_OWNED_KEYS",
    "REPO_OWNED_KEYS",
    "build_policy",
    "filter_policy_layer_cfg",
    "load_config",
    "_flatten_sections",
]

DEFAULT_BADGUYS_COMMAND = ["badguys/badguys.py", "-q"]


@dataclass
class Policy(PolicyMonolithMixin):
    _src: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        from dataclasses import fields

        for f in fields(self):
            if f.name == "_src":
                continue
            self._src.setdefault(f.name, "default")

    repo_root: str | None = None
    artifacts_root: str | None = None
    target_repo_roots: list[str] = field(default_factory=list)
    active_target_repo_root: str | None = None
    patch_dir: str | None = None
    target_repo_name: str = ""
    target_repo_config_relpath: str = ".am_patch/am_patch.repo.toml"
    patch_dir_name: str = "patches"

    patch_layout_logs_dir: str = "logs"
    patch_layout_json_dir: str = "logs_json"
    patch_layout_workspaces_dir: str = "workspaces"
    patch_layout_successful_dir: str = "successful"
    patch_layout_unsuccessful_dir: str = "unsuccessful"

    lockfile_name: str = "am_patch.lock"
    current_log_symlink_name: str = "am_patch.log"
    current_log_symlink_enabled: bool = True

    log_ts_format: str = "%Y%m%d_%H%M%S"
    log_template_issue: str = "am_patch_issue_{issue}_{ts}.log"
    log_template_finalize: str = "am_patch_finalize_{ts}.log"

    failure_zip_name: str = "patched.zip"
    failure_zip_template: str = ""
    failure_zip_cleanup_glob_template: str = "patched_issue{issue}_*.zip"
    failure_zip_keep_per_issue: int = 1
    failure_zip_delete_on_success_commit: bool = True
    failure_zip_log_dir: str = "logs"
    failure_zip_patch_dir: str = "patches"

    self_backup_mode: str = "initial_self_patch"
    self_backup_dir: str = "quarantine"
    self_backup_template: str = "amp_self_backup_issue{issue}_{ts}.zip"
    self_backup_include_relpaths: list[str] = field(
        default_factory=lambda: ["scripts/am_patch.py", "scripts/am_patch/"]
    )
    workspace_issue_dir_template: str = "issue_{issue}"
    workspace_repo_dir_name: str = "repo"
    workspace_meta_filename: str = "meta.json"

    workspace_history_logs_dir: str = "logs"
    workspace_history_oldlogs_dir: str = "oldlogs"
    workspace_history_patches_dir: str = "patches"
    workspace_history_oldpatches_dir: str = "oldpatches"

    blessed_gate_outputs: list[str] = field(
        default_factory=lambda: ["audit/results/pytest_junit.xml"]
    )
    scope_ignore_prefixes: list[str] = field(
        default_factory=lambda: [
            ".am_patch/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            "__pycache__/",
        ]
    )
    scope_ignore_suffixes: list[str] = field(default_factory=lambda: [".pyc"])
    scope_ignore_contains: list[str] = field(default_factory=lambda: ["/__pycache__/"])

    venv_bootstrap_mode: str = "auto"  # auto|always|never
    venv_bootstrap_python: str = ".venv/bin/python"

    python_gate_mode: str = "auto"
    python_gate_python: str = ".venv/bin/python"

    default_branch: str = "main"

    success_archive_name: str = "{repo}-{branch}.zip"

    success_archive_dir: str = "patch_dir"
    success_archive_cleanup_glob_template: str = ""
    success_archive_keep_count: int = 0

    require_up_to_date: bool = True
    enforce_main_branch: bool = True

    update_workspace: bool = False
    soft_reset_workspace: bool = False
    test_mode: bool = False
    test_mode_isolate_patch_dir: bool = True
    delete_workspace_on_success: bool = True

    ascii_only_patch: bool = True

    verbosity: str = "verbose"

    log_level: str = "verbose"

    runner_subprocess_timeout_s: int = 1800

    json_out: bool = False

    # Console output coloring for OK/FAIL tokens.
    console_color: str = "auto"  # auto|always|never

    # IPC socket (UDS, NDJSON)
    ipc_socket_enabled: bool = True
    ipc_socket_mode: str = "patch_dir"  # patch_dir|base_dir|system_runtime
    ipc_socket_path: str | None = None
    ipc_socket_name_template: str = "am_patch_ipc_{issue}_{pid}.sock"
    ipc_socket_name: str = "am_patch.sock"
    ipc_socket_base_dir: str | None = None
    ipc_socket_system_runtime_dir: str | None = None
    ipc_socket_cleanup_delay_success_s: int = 0
    ipc_socket_cleanup_delay_failure_s: int = 0
    ipc_socket_on_startup_exists: str = "fail"
    ipc_socket_on_startup_wait_s: int = 0
    ipc_handshake_enabled: bool = False
    ipc_handshake_wait_s: int = 0

    unified_patch: bool = False
    unified_patch_continue: bool = True
    unified_patch_strip: int | None = None  # None=infer
    unified_patch_touch_on_fail: bool = True
    no_op_fail: bool = True
    allow_no_op: bool = False
    enforce_allowed_files: bool = True

    run_all_tests: bool = True
    compile_check: bool = True
    compile_targets: list[str] = field(default_factory=lambda: ["."])
    compile_exclude: list[str] = field(default_factory=list)
    ruff_autofix: bool = True
    ruff_autofix_legalize_outside: bool = True

    ruff_format: bool = True

    biome_format: bool = True
    biome_format_legalize_outside: bool = True
    gate_biome_format_command: list[str] = field(
        default_factory=lambda: ["npm", "exec", "--", "biome", "format", "--write"]
    )

    gates_allow_fail: bool = False
    gates_skip_dont_touch: bool = False
    dont_touch_paths: list[str] = field(
        default_factory=lambda: [
            "scripts/patchhub/static/patchhub_bootstrap.js",
            "tsconfig.json",
            "biome.json",
            "pyproject.toml",
        ]
    )
    gates_skip_ruff: bool = False
    gates_skip_pytest: bool = False
    gates_skip_mypy: bool = False
    gates_skip_docs: bool = False

    gates_skip_js: bool = False
    gate_js_extensions: list[str] = field(default_factory=lambda: [".js"])
    gate_js_command: list[str] = field(default_factory=lambda: ["node", "--check"])

    gates_skip_biome: bool = True
    gate_biome_extensions: list[str] = field(
        default_factory=lambda: [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]
    )
    gate_biome_command: list[str] = field(
        default_factory=lambda: ["npm", "run", "lint:files", "--"]
    )
    biome_autofix: bool = True
    biome_autofix_legalize_outside: bool = True
    gate_biome_fix_command: list[str] = field(
        default_factory=lambda: ["npm", "run", "lint:files:fix", "--"]
    )

    gates_skip_typescript: bool = True
    gate_typescript_extensions: list[str] = field(
        default_factory=lambda: [".ts", ".tsx", ".mts", ".cts"]
    )
    gate_typescript_command: list[str] = field(
        default_factory=lambda: ["tsc", "--noEmit", "--pretty", "false"]
    )

    gate_typescript_mode: str = "auto"
    typescript_targets: list[str] = field(default_factory=list)
    gate_typescript_base_tsconfig: str = "tsconfig.json"
    apply_failure_partial_gates_policy: str = "repair_only"
    apply_failure_zero_gates_policy: str = "never"
    gate_docs_include: list[str] = field(default_factory=lambda: ["src", "plugins"])
    gate_docs_exclude: list[str] = field(default_factory=lambda: ["badguys", "patches"])
    gate_docs_required_files: list[str] = field(default_factory=lambda: ["docs/change_fragments/"])
    gates_order: list[str] = field(
        default_factory=lambda: [
            "dont-touch",
            "compile",
            "js",
            "biome",
            "typescript",
            "ruff",
            "pytest",
            "mypy",
            "monolith",
            "docs",
            "badguys",
        ]
    )
    gates_skip_badguys: bool = False
    gate_badguys_mode: str = "auto"
    gate_badguys_trigger_prefixes: list[str] = field(default_factory=list)
    gate_badguys_trigger_files: list[str] = field(default_factory=list)
    gate_badguys_command: list[str] = field(default_factory=lambda: list(DEFAULT_BADGUYS_COMMAND))
    ruff_targets: list[str] = field(default_factory=lambda: ["src", "tests"])
    pytest_targets: list[str] = field(default_factory=lambda: ["tests"])
    mypy_targets: list[str] = field(default_factory=lambda: ["src"])

    gate_ruff_mode: str = "auto"
    gate_mypy_mode: str = "auto"
    gate_pytest_mode: str = "auto"
    gate_pytest_py_prefixes: list[str] = field(
        default_factory=lambda: ["tests", "src", "plugins", "scripts"]
    )
    gate_pytest_js_prefixes: list[str] = field(default_factory=list)
    pytest_routing_mode: str = "bucketed"
    pytest_roots: dict[str, str] = field(default_factory=lambda: deepcopy(PYTEST_ROOTS_DEFAULT))
    pytest_tree: dict[str, str] = field(default_factory=lambda: deepcopy(PYTEST_TREE_DEFAULT))
    pytest_namespace_modules: dict[str, list[str]] = field(
        default_factory=lambda: deepcopy(PYTEST_NAMESPACE_MODULES_DEFAULT)
    )
    pytest_dependencies: dict[str, list[str]] = field(
        default_factory=lambda: deepcopy(PYTEST_DEPENDENCIES_DEFAULT)
    )
    pytest_external_dependencies: dict[str, list[str]] = field(
        default_factory=lambda: deepcopy(PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT)
    )
    pytest_full_suite_prefixes: list[str] = field(
        default_factory=lambda: list(PYTEST_FULL_SUITE_PREFIXES_DEFAULT)
    )

    pytest_use_venv: bool = True

    fail_if_live_files_changed: bool = True
    live_changed_resolution: str = "fail"  # fail|overwrite_live|overwrite_workspace

    commit_and_push: bool = True

    post_success_audit: bool = True

    no_rollback: bool = False

    rollback_workspace_on_fail: str = "none-applied"

    live_repo_guard: bool = True

    live_repo_guard_scope: str = "patch"

    audit_rubric_guard: bool = False

    patch_jail: bool = True
    patch_jail_unshare_net: bool = True

    skip_up_to_date: bool = False
    allow_non_main: bool = False
    allow_push_fail: bool = True
    declared_untouched_fail: bool = True
    allow_declared_untouched: bool = False
    allow_outside_files: bool = False


REPO_OWNED_KEY_GROUPS: tuple[tuple[str, ...], ...] = (
    ("allow_declared_untouched", "allow_outside_files", "allow_push_fail"),
    ("apply_failure_partial_gates_policy", "apply_failure_zero_gates_policy"),
    ("ascii_only_patch", "audit_rubric_guard", "biome_autofix"),
    ("biome_autofix_legalize_outside", "biome_format", "biome_format_legalize_outside"),
    ("blessed_gate_outputs", "commit_and_push", "compile_check", "compile_exclude"),
    ("compile_targets", "declared_untouched_fail", "default_branch", "dont_touch_paths"),
    ("enforce_allowed_files", "enforce_main_branch", "fail_if_live_files_changed"),
    ("gate_badguys_command", "gate_badguys_mode", "gate_badguys_trigger_files"),
    ("gate_biome_command", "gate_biome_extensions", "gate_biome_fix_command"),
    ("gate_biome_format_command", "gate_docs_exclude", "gate_docs_include"),
    ("gate_docs_required_files", "gate_js_command", "gate_js_extensions"),
    ("gate_monolith_areas_dynamic", "gate_monolith_areas_names"),
    ("gate_monolith_areas_prefixes", "gate_monolith_catchall_allowlist"),
    ("gate_monolith_catchall_basenames", "gate_monolith_catchall_dirs"),
    ("gate_monolith_compute_fanin", "gate_monolith_crossarea_min_distinct_areas"),
    ("gate_monolith_enabled", "gate_monolith_extensions"),
    ("gate_monolith_hub_exports_delta_min", "gate_monolith_hub_fanin_delta"),
    ("gate_monolith_hub_fanout_delta", "gate_monolith_hub_loc_delta_min"),
    ("gate_monolith_huge_allow_exports_delta", "gate_monolith_huge_allow_imports_delta"),
    ("gate_monolith_huge_allow_loc_increase", "gate_monolith_huge_loc"),
    ("gate_monolith_large_allow_exports_delta", "gate_monolith_large_allow_imports_delta"),
    ("gate_monolith_large_allow_loc_increase", "gate_monolith_large_loc"),
    ("gate_monolith_mode", "gate_monolith_new_file_max_exports"),
    ("gate_monolith_new_file_max_imports", "gate_monolith_new_file_max_loc"),
    ("gate_monolith_on_parse_error", "gate_monolith_scan_scope", "gate_mypy_mode"),
    ("gate_pytest_js_prefixes", "gate_pytest_py_prefixes", "gate_pytest_mode"),
    ("gate_ruff_mode", "gate_typescript_base_tsconfig", "gate_typescript_command"),
    ("gate_typescript_extensions", "gate_typescript_mode", "gates_allow_fail"),
    ("gates_skip_badguys", "gates_skip_biome", "gates_skip_docs", "gates_skip_dont_touch"),
    ("gates_skip_js", "gates_skip_monolith", "gates_skip_mypy", "gates_skip_pytest"),
    ("gates_skip_ruff", "gates_skip_typescript", "live_changed_resolution", "mypy_targets"),
    ("no_rollback", "post_success_audit", "pytest_dependencies"),
    ("pytest_external_dependencies", "pytest_full_suite_prefixes"),
    ("pytest_namespace_modules", "pytest_roots", "pytest_routing_mode", "pytest_targets"),
    ("pytest_tree", "pytest_use_venv", "python_gate_mode", "python_gate_python"),
    ("require_up_to_date", "ruff_autofix", "ruff_autofix_legalize_outside", "ruff_format"),
    ("no_op_fail", "ruff_targets", "scope_ignore_contains", "scope_ignore_prefixes"),
    ("gate_badguys_trigger_prefixes", "scope_ignore_suffixes", "typescript_targets"),
)


REPO_OWNED_KEYS: set[str] = {key for group in REPO_OWNED_KEY_GROUPS for key in group}


def _policy_field_names() -> set[str]:
    return {name for name in Policy.__dataclass_fields__ if name != "_src"}


BOOTSTRAP_OWNED_KEYS: set[str] = _policy_field_names() - REPO_OWNED_KEYS


def filter_policy_layer_cfg(
    cfg: dict[str, Any],
    allowed_keys: set[str],
) -> dict[str, Any]:
    return {key: value for key, value in cfg.items() if key in allowed_keys}


def _as_bool(d: dict[str, Any], k: str, default: bool) -> bool:
    return bool(d.get(k, default))


def _as_str(d: dict[str, Any], k: str, default: str | None) -> str | None:
    v = d.get(k, default)
    return None if v is None else str(v)


def _as_str_required(d: dict[str, Any], k: str, default: str) -> str:
    v = _as_str(d, k, default)
    assert v is not None
    return v


def _as_rollback_mode(d: dict[str, Any], k: str, default: str) -> str:
    v = d.get(k, default)
    if isinstance(v, bool):
        return "none-applied" if v else "never"
    if not isinstance(v, str):
        raise TypeError(f"config key {k!r} must be a string or bool, got {type(v).__name__}")
    if v not in ("none-applied", "always", "never"):
        raise ValueError(f"config key {k!r} has invalid value {v!r}")
    return v


def _as_dict_list_str(
    d: dict[str, Any],
    k: str,
    default: dict[str, list[str]],
) -> dict[str, list[str]]:
    v = d.get(k)
    if v is None:
        return deepcopy(default)
    if not isinstance(v, dict):
        return deepcopy(default)
    out: dict[str, list[str]] = {}
    for key, raw_value in v.items():
        skey = str(key).strip()
        if not skey:
            continue
        if isinstance(raw_value, list):
            out[skey] = [str(item).strip() for item in raw_value if str(item).strip()]
            continue
        if isinstance(raw_value, str):
            sval = raw_value.strip()
            out[skey] = [sval] if sval else []
    return out


def _as_list_str(
    d: dict[str, Any], k: str, default: list[str], *, preserve_empty: bool = False
) -> list[str]:
    v = d.get(k)
    if v is None:
        return list(default)
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if not isinstance(x, str):
                continue
            s = x.strip()
            if s and s not in out:
                out.append(s)
        return out if preserve_empty else (out or list(default))
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else ([] if preserve_empty else list(default))
    return list(default)


def _validate_basename(v: str, *, field: str) -> str:
    s = str(v).strip()
    if not s:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be non-empty")
    if "/" in s or "\\" in s:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{field} must be a basename (no path separators): {s!r}",
        )
    return s


def _validate_ascii_single_line(v: str, *, field: str) -> str:
    s = str(v).strip()
    if not s:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be non-empty")
    if "\n" in s or "\r" in s:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be a single line")
    try:
        s.encode("ascii")
    except UnicodeEncodeError as e:
        raise RunnerError("CONFIG", "INVALID", f"{field} must be ASCII-only") from e
    return s


def _validate_repo_token(v: str, *, field: str) -> str:
    s = _validate_ascii_single_line(v, field=field)
    if any(ch.isspace() for ch in s):
        raise RunnerError("CONFIG", "INVALID", f"{field} must not contain whitespace")
    if "/" in s or "\\" in s:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"{field} must be a bare token (no path separators): {s!r}",
        )
    return s


def _parse_override_kv(s: str) -> tuple[str, object]:
    if "=" not in s:
        raise ValueError("override must be KEY=VALUE")
    k, v = s.split("=", 1)
    k = k.strip()
    v = v.strip()
    if v.lower() in ("true", "false"):
        return k, (v.lower() == "true")
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return k, []
        return k, [x.strip().strip("'\"") for x in inner.split(",")]
    if "," in v:
        return k, [x.strip().strip("'\"") for x in v.split(",")]
    if re.fullmatch(r"-?\d+", v):
        return k, int(v)
    return k, v


def _coerce_override_value(cur: object, raw: object) -> object:
    if isinstance(cur, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
        raise RunnerError("CONFIG", "INVALID", f"invalid boolean override: {raw!r}")

    if isinstance(cur, int):
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw.strip())
            except Exception as e:
                raise RunnerError("CONFIG", "INVALID", f"invalid integer override: {raw!r}") from e
        raise RunnerError("CONFIG", "INVALID", f"invalid integer override: {raw!r}")

    if isinstance(cur, list):
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            parts = [p for p in (x.strip() for x in raw.split(",")) if p]
            return parts
        raise RunnerError("CONFIG", "INVALID", f"invalid list override: {raw!r}")

    return raw


def _mark_cfg(
    p: Policy,
    cfg: dict[str, Any],
    key: str,
    source_name: str = "config",
) -> None:
    if key in cfg:
        p._src[key] = source_name


def build_policy(
    defaults: Policy,
    cfg: dict[str, Any],
    *,
    source_name: str = "config",
) -> Policy:
    _fields = getattr(Policy, "__dataclass_fields__", {})
    _kwargs = {
        k: v
        for k, v in defaults.__dict__.items()
        if k in _fields and getattr(_fields[k], "init", True)
    }
    p = Policy(**_kwargs)
    p._src = dict(getattr(defaults, "_src", {}))
    for field_name in _policy_field_names():
        p._src.setdefault(field_name, "default")

    p.repo_root = _as_str(cfg, "repo_root", p.repo_root)
    _mark_cfg(p, cfg, "repo_root")
    p.artifacts_root = _as_str(cfg, "artifacts_root", p.artifacts_root)
    _mark_cfg(p, cfg, "artifacts_root")
    p.target_repo_roots = _as_list_str(cfg, "target_repo_roots", p.target_repo_roots)
    _mark_cfg(p, cfg, "target_repo_roots")
    p.active_target_repo_root = _as_str(cfg, "active_target_repo_root", p.active_target_repo_root)
    _mark_cfg(p, cfg, "active_target_repo_root")
    p.patch_dir = _as_str(cfg, "patch_dir", p.patch_dir)
    _mark_cfg(p, cfg, "patch_dir")
    p.target_repo_name = _as_str_required(cfg, "target_repo_name", p.target_repo_name)
    _mark_cfg(p, cfg, "target_repo_name")
    p.target_repo_config_relpath = _as_str_required(
        cfg,
        "target_repo_config_relpath",
        p.target_repo_config_relpath,
    )
    _mark_cfg(p, cfg, "target_repo_config_relpath")
    p.patch_dir_name = str(cfg.get("patch_dir_name", p.patch_dir_name))
    _mark_cfg(p, cfg, "patch_dir_name")

    p.patch_layout_logs_dir = str(cfg.get("patch_layout_logs_dir", p.patch_layout_logs_dir))
    _mark_cfg(p, cfg, "patch_layout_logs_dir")
    p.patch_layout_workspaces_dir = str(
        cfg.get("patch_layout_workspaces_dir", p.patch_layout_workspaces_dir)
    )
    _mark_cfg(p, cfg, "patch_layout_workspaces_dir")
    p.patch_layout_successful_dir = str(
        cfg.get("patch_layout_successful_dir", p.patch_layout_successful_dir)
    )
    _mark_cfg(p, cfg, "patch_layout_successful_dir")
    p.patch_layout_unsuccessful_dir = str(
        cfg.get("patch_layout_unsuccessful_dir", p.patch_layout_unsuccessful_dir)
    )
    _mark_cfg(p, cfg, "patch_layout_unsuccessful_dir")

    p.lockfile_name = str(cfg.get("lockfile_name", p.lockfile_name))
    _mark_cfg(p, cfg, "lockfile_name")
    p.current_log_symlink_name = str(
        cfg.get("current_log_symlink_name", p.current_log_symlink_name)
    )
    _mark_cfg(p, cfg, "current_log_symlink_name")
    p.current_log_symlink_enabled = _as_bool(
        cfg, "current_log_symlink_enabled", p.current_log_symlink_enabled
    )
    _mark_cfg(p, cfg, "current_log_symlink_enabled")

    p.log_ts_format = str(cfg.get("log_ts_format", p.log_ts_format))
    _mark_cfg(p, cfg, "log_ts_format")
    p.log_template_issue = str(cfg.get("log_template_issue", p.log_template_issue))
    _mark_cfg(p, cfg, "log_template_issue")
    p.log_template_finalize = str(cfg.get("log_template_finalize", p.log_template_finalize))
    _mark_cfg(p, cfg, "log_template_finalize")

    p.failure_zip_name = str(cfg.get("failure_zip_name", p.failure_zip_name))
    _mark_cfg(p, cfg, "failure_zip_name")
    p.failure_zip_template = str(cfg.get("failure_zip_template", p.failure_zip_template))
    _mark_cfg(p, cfg, "failure_zip_template")
    p.failure_zip_cleanup_glob_template = str(
        cfg.get("failure_zip_cleanup_glob_template", p.failure_zip_cleanup_glob_template)
    )
    _mark_cfg(p, cfg, "failure_zip_cleanup_glob_template")
    if "failure_zip_keep_per_issue" in cfg:
        p.failure_zip_keep_per_issue = int(cfg["failure_zip_keep_per_issue"])
        _mark_cfg(p, cfg, "failure_zip_keep_per_issue")
    p.failure_zip_delete_on_success_commit = _as_bool(
        cfg,
        "failure_zip_delete_on_success_commit",
        p.failure_zip_delete_on_success_commit,
    )
    _mark_cfg(p, cfg, "failure_zip_delete_on_success_commit")
    p.failure_zip_log_dir = str(cfg.get("failure_zip_log_dir", p.failure_zip_log_dir))
    _mark_cfg(p, cfg, "failure_zip_log_dir")
    p.failure_zip_patch_dir = str(cfg.get("failure_zip_patch_dir", p.failure_zip_patch_dir))
    _mark_cfg(p, cfg, "failure_zip_patch_dir")

    for key in ("self_backup_mode", "self_backup_dir", "self_backup_template"):
        setattr(p, key, _as_str_required(cfg, key, getattr(p, key)))
        _mark_cfg(p, cfg, key)
    p.self_backup_include_relpaths = _as_list_str(
        cfg, "self_backup_include_relpaths", p.self_backup_include_relpaths, preserve_empty=True
    )
    _mark_cfg(p, cfg, "self_backup_include_relpaths")
    p.workspace_issue_dir_template = str(
        cfg.get("workspace_issue_dir_template", p.workspace_issue_dir_template)
    )
    _mark_cfg(p, cfg, "workspace_issue_dir_template")
    p.workspace_repo_dir_name = str(cfg.get("workspace_repo_dir_name", p.workspace_repo_dir_name))
    _mark_cfg(p, cfg, "workspace_repo_dir_name")
    p.workspace_meta_filename = str(cfg.get("workspace_meta_filename", p.workspace_meta_filename))
    _mark_cfg(p, cfg, "workspace_meta_filename")

    p.workspace_history_logs_dir = str(
        cfg.get("workspace_history_logs_dir", p.workspace_history_logs_dir)
    )
    _mark_cfg(p, cfg, "workspace_history_logs_dir")
    p.workspace_history_oldlogs_dir = str(
        cfg.get("workspace_history_oldlogs_dir", p.workspace_history_oldlogs_dir)
    )
    _mark_cfg(p, cfg, "workspace_history_oldlogs_dir")
    p.workspace_history_patches_dir = str(
        cfg.get("workspace_history_patches_dir", p.workspace_history_patches_dir)
    )
    _mark_cfg(p, cfg, "workspace_history_patches_dir")
    p.workspace_history_oldpatches_dir = str(
        cfg.get("workspace_history_oldpatches_dir", p.workspace_history_oldpatches_dir)
    )
    _mark_cfg(p, cfg, "workspace_history_oldpatches_dir")

    p.blessed_gate_outputs = _as_list_str(cfg, "blessed_gate_outputs", p.blessed_gate_outputs)
    _mark_cfg(p, cfg, "blessed_gate_outputs")
    p.scope_ignore_prefixes = _as_list_str(cfg, "scope_ignore_prefixes", p.scope_ignore_prefixes)
    _mark_cfg(p, cfg, "scope_ignore_prefixes")
    p.scope_ignore_suffixes = _as_list_str(cfg, "scope_ignore_suffixes", p.scope_ignore_suffixes)
    _mark_cfg(p, cfg, "scope_ignore_suffixes")
    p.scope_ignore_contains = _as_list_str(cfg, "scope_ignore_contains", p.scope_ignore_contains)
    _mark_cfg(p, cfg, "scope_ignore_contains")

    p.venv_bootstrap_mode = str(cfg.get("venv_bootstrap_mode", p.venv_bootstrap_mode))
    _mark_cfg(p, cfg, "venv_bootstrap_mode")
    p.venv_bootstrap_python = str(cfg.get("venv_bootstrap_python", p.venv_bootstrap_python))
    _mark_cfg(p, cfg, "venv_bootstrap_python")

    p.python_gate_mode = str(cfg.get("python_gate_mode", p.python_gate_mode))
    _mark_cfg(p, cfg, "python_gate_mode")
    if p.python_gate_mode not in ("runner", "auto", "required"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "python_gate_mode must be runner|auto|required",
        )
    p.python_gate_python = str(cfg.get("python_gate_python", p.python_gate_python))
    _mark_cfg(p, cfg, "python_gate_python")

    p.default_branch = str(cfg.get("default_branch", p.default_branch))
    _mark_cfg(p, cfg, "default_branch")
    p.success_archive_name = str(cfg.get("success_archive_name", p.success_archive_name))
    _mark_cfg(p, cfg, "success_archive_name")

    p.success_archive_dir = str(cfg.get("success_archive_dir", p.success_archive_dir))
    _mark_cfg(p, cfg, "success_archive_dir")
    p.success_archive_cleanup_glob_template = str(
        cfg.get(
            "success_archive_cleanup_glob_template",
            p.success_archive_cleanup_glob_template,
        )
    )
    _mark_cfg(p, cfg, "success_archive_cleanup_glob_template")
    if "success_archive_keep_count" in cfg:
        p.success_archive_keep_count = int(cfg["success_archive_keep_count"])
        _mark_cfg(p, cfg, "success_archive_keep_count")

    p.require_up_to_date = _as_bool(cfg, "require_up_to_date", p.require_up_to_date)
    _mark_cfg(p, cfg, "require_up_to_date")
    p.enforce_main_branch = _as_bool(cfg, "enforce_main_branch", p.enforce_main_branch)
    _mark_cfg(p, cfg, "enforce_main_branch")

    p.update_workspace = _as_bool(cfg, "update_workspace", p.update_workspace)
    _mark_cfg(p, cfg, "update_workspace")
    p.soft_reset_workspace = _as_bool(cfg, "soft_reset_workspace", p.soft_reset_workspace)
    _mark_cfg(p, cfg, "soft_reset_workspace")
    p.delete_workspace_on_success = _as_bool(
        cfg, "delete_workspace_on_success", p.delete_workspace_on_success
    )
    _mark_cfg(p, cfg, "delete_workspace_on_success")
    p.test_mode = _as_bool(cfg, "test_mode", p.test_mode)
    _mark_cfg(p, cfg, "test_mode")
    p.test_mode_isolate_patch_dir = _as_bool(
        cfg, "test_mode_isolate_patch_dir", p.test_mode_isolate_patch_dir
    )
    _mark_cfg(p, cfg, "test_mode_isolate_patch_dir")

    p.ascii_only_patch = _as_bool(cfg, "ascii_only_patch", p.ascii_only_patch)
    _mark_cfg(p, cfg, "ascii_only_patch")
    allowed_levels = ("debug", "verbose", "normal", "warning", "quiet")

    p.verbosity = str(cfg.get("verbosity", p.verbosity))
    _mark_cfg(p, cfg, "verbosity")
    if p.verbosity not in allowed_levels:
        raise RunnerError(
            "CONFIG",
            "INVALID_VERBOSITY",
            f"invalid verbosity={p.verbosity!r}; allowed: debug|verbose|normal|warning|quiet",
        )

    p.log_level = str(cfg.get("log_level", p.log_level))
    _mark_cfg(p, cfg, "log_level")
    if p.log_level not in allowed_levels:
        raise RunnerError(
            "CONFIG",
            "INVALID_LOG_LEVEL",
            f"invalid log_level={p.log_level!r}; allowed: debug|verbose|normal|warning|quiet",
        )

    if "runner_subprocess_timeout_s" in cfg:
        p.runner_subprocess_timeout_s = int(cfg["runner_subprocess_timeout_s"])
        _mark_cfg(p, cfg, "runner_subprocess_timeout_s")
    if p.runner_subprocess_timeout_s < 0:
        raise RunnerError("CONFIG", "INVALID", "runner_subprocess_timeout_s must be >= 0")

    p.console_color = str(cfg.get("console_color", p.console_color))
    _mark_cfg(p, cfg, "console_color")
    if p.console_color not in ("auto", "always", "never"):
        raise RunnerError(
            "CONFIG",
            "INVALID_CONSOLE_COLOR",
            f"invalid console_color={p.console_color!r}; allowed: auto|always|never",
        )

    apply_ipc_cfg_surface(
        p,
        cfg,
        as_bool=_as_bool,
        mark_cfg=_mark_cfg,
    )

    p.target_repo_name = str(p.target_repo_name or "").strip()
    if p.target_repo_name:
        p.target_repo_name = _validate_repo_token(p.target_repo_name, field="target_repo_name")
    p.target_repo_config_relpath = str(p.target_repo_config_relpath or "").strip()
    if not p.target_repo_config_relpath:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "target_repo_config_relpath must be non-empty",
        )
    p.patch_dir_name = _validate_basename(p.patch_dir_name, field="patch_dir_name")
    p.patch_layout_logs_dir = _validate_basename(
        p.patch_layout_logs_dir, field="patch_layout_logs_dir"
    )
    p.patch_layout_workspaces_dir = _validate_basename(
        p.patch_layout_workspaces_dir, field="patch_layout_workspaces_dir"
    )
    p.patch_layout_successful_dir = _validate_basename(
        p.patch_layout_successful_dir, field="patch_layout_successful_dir"
    )
    p.patch_layout_unsuccessful_dir = _validate_basename(
        p.patch_layout_unsuccessful_dir, field="patch_layout_unsuccessful_dir"
    )
    p.lockfile_name = _validate_basename(p.lockfile_name, field="lockfile_name")
    p.current_log_symlink_name = _validate_basename(
        p.current_log_symlink_name, field="current_log_symlink_name"
    )
    p.failure_zip_name = _validate_basename(p.failure_zip_name, field="failure_zip_name")

    p.failure_zip_template = str(p.failure_zip_template).strip()
    if p.failure_zip_template and "{issue}" not in p.failure_zip_template:
        raise RunnerError("CONFIG", "INVALID", "failure_zip_template must contain {issue}")

    if p.failure_zip_template:
        uniqueness_keys = ("{ts}", "{nonce}", "{attempt")
        if not any(k in p.failure_zip_template for k in uniqueness_keys):
            raise RunnerError(
                "CONFIG",
                "INVALID",
                "failure_zip_template must contain at least one of {ts}, {nonce}, {attempt}",
            )

    p.failure_zip_cleanup_glob_template = _validate_basename(
        p.failure_zip_cleanup_glob_template,
        field="failure_zip_cleanup_glob_template",
    )
    if p.failure_zip_keep_per_issue < 0:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "failure_zip_keep_per_issue must be >= 0",
        )
    validate_success_archive_retention(p)
    p.failure_zip_log_dir = _validate_basename(p.failure_zip_log_dir, field="failure_zip_log_dir")
    p.failure_zip_patch_dir = _validate_basename(
        p.failure_zip_patch_dir, field="failure_zip_patch_dir"
    )

    normalize_self_backup_policy(p)

    p.workspace_issue_dir_template = str(p.workspace_issue_dir_template).strip() or "issue_{issue}"
    p.workspace_repo_dir_name = _validate_basename(
        p.workspace_repo_dir_name, field="workspace_repo_dir_name"
    )
    p.workspace_meta_filename = _validate_basename(
        p.workspace_meta_filename, field="workspace_meta_filename"
    )

    p.workspace_history_logs_dir = _validate_basename(
        p.workspace_history_logs_dir, field="workspace_history_logs_dir"
    )
    p.workspace_history_oldlogs_dir = _validate_basename(
        p.workspace_history_oldlogs_dir, field="workspace_history_oldlogs_dir"
    )
    p.workspace_history_patches_dir = _validate_basename(
        p.workspace_history_patches_dir, field="workspace_history_patches_dir"
    )
    p.workspace_history_oldpatches_dir = _validate_basename(
        p.workspace_history_oldpatches_dir, field="workspace_history_oldpatches_dir"
    )

    if "{ts}" not in p.log_template_issue or "{issue}" not in p.log_template_issue:
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "log_template_issue must contain {issue} and {ts}",
        )
    if "{ts}" not in p.log_template_finalize:
        raise RunnerError("CONFIG", "INVALID", "log_template_finalize must contain {ts}")

    if p.venv_bootstrap_mode not in ("auto", "always", "never"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"invalid venv_bootstrap_mode={p.venv_bootstrap_mode!r}; allowed: auto|always|never",
        )
    if not str(p.venv_bootstrap_python).strip():
        raise RunnerError("CONFIG", "INVALID", "venv_bootstrap_python must be non-empty")

    p.no_op_fail = _as_bool(cfg, "no_op_fail", p.no_op_fail)
    _mark_cfg(p, cfg, "no_op_fail")
    p.allow_no_op = _as_bool(cfg, "allow_no_op", p.allow_no_op)
    _mark_cfg(p, cfg, "allow_no_op")
    p.enforce_allowed_files = _as_bool(cfg, "enforce_allowed_files", p.enforce_allowed_files)
    _mark_cfg(p, cfg, "enforce_allowed_files")

    apply_gate_execution_cfg(
        cfg,
        p,
        as_bool=_as_bool,
        as_str_required=_as_str_required,
        as_list_str=_as_list_str,
        as_dict_list_str=_as_dict_list_str,
        mark_cfg=_mark_cfg,
    )

    p.fail_if_live_files_changed = _as_bool(
        cfg, "fail_if_live_files_changed", p.fail_if_live_files_changed
    )
    _mark_cfg(p, cfg, "fail_if_live_files_changed")

    p.live_changed_resolution = str(cfg.get("live_changed_resolution", p.live_changed_resolution))
    _mark_cfg(p, cfg, "live_changed_resolution")
    if p.live_changed_resolution not in (
        "fail",
        "overwrite_live",
        "overwrite_workspace",
    ):
        raise RunnerError(
            "CONFIG",
            "INVALID_LIVE_CHANGED_RESOLUTION",
            (
                f"invalid live_changed_resolution={p.live_changed_resolution!r}; allowed: "
                "fail|overwrite_live|overwrite_workspace"
            ),
        )
    p.commit_and_push = _as_bool(cfg, "commit_and_push", p.commit_and_push)
    _mark_cfg(p, cfg, "commit_and_push")

    p.post_success_audit = _as_bool(cfg, "post_success_audit", p.post_success_audit)
    _mark_cfg(p, cfg, "post_success_audit")

    p.no_rollback = _as_bool(cfg, "no_rollback", p.no_rollback)
    _mark_cfg(p, cfg, "no_rollback")

    p.rollback_workspace_on_fail = _as_rollback_mode(
        cfg, "rollback_workspace_on_fail", p.rollback_workspace_on_fail
    )
    _mark_cfg(p, cfg, "rollback_workspace_on_fail")
    p.live_repo_guard = _as_bool(cfg, "live_repo_guard", p.live_repo_guard)
    _mark_cfg(p, cfg, "live_repo_guard")
    p.live_repo_guard_scope = str(cfg.get("live_repo_guard_scope", p.live_repo_guard_scope))
    _mark_cfg(p, cfg, "live_repo_guard_scope")
    p.patch_jail = _as_bool(cfg, "patch_jail", p.patch_jail)
    _mark_cfg(p, cfg, "patch_jail")
    p.patch_jail_unshare_net = _as_bool(cfg, "patch_jail_unshare_net", p.patch_jail_unshare_net)
    _mark_cfg(p, cfg, "patch_jail_unshare_net")

    p.skip_up_to_date = _as_bool(cfg, "skip_up_to_date", p.skip_up_to_date)
    _mark_cfg(p, cfg, "skip_up_to_date")
    p.allow_non_main = _as_bool(cfg, "allow_non_main", p.allow_non_main)
    _mark_cfg(p, cfg, "allow_non_main")

    p.allow_push_fail = _as_bool(cfg, "allow_push_fail", p.allow_push_fail)
    _mark_cfg(p, cfg, "allow_push_fail")

    p.allow_outside_files = _as_bool(cfg, "allow_outside_files", p.allow_outside_files)
    _mark_cfg(p, cfg, "allow_outside_files")
    p.declared_untouched_fail = _as_bool(cfg, "declared_untouched_fail", p.declared_untouched_fail)
    _mark_cfg(p, cfg, "declared_untouched_fail")
    p.allow_declared_untouched = _as_bool(
        cfg, "allow_declared_untouched", p.allow_declared_untouched
    )
    _mark_cfg(p, cfg, "allow_declared_untouched")

    p.audit_rubric_guard = _as_bool(cfg, "audit_rubric_guard", p.audit_rubric_guard)
    _mark_cfg(p, cfg, "audit_rubric_guard")

    if p.live_repo_guard_scope not in ("patch", "patch_and_gates"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            f"invalid live_repo_guard_scope={p.live_repo_guard_scope!r}",
        )

    if source_name != "config":
        for key in cfg:
            if key in p._src and p._src.get(key) == "config":
                p._src[key] = source_name

    return p


def apply_cli_overrides(p: Policy, mapping: dict[str, object | None]) -> None:
    for k, v in mapping.items():
        if v is None:
            continue
        if not hasattr(p, k):
            continue
        if k == "target_repo_name":
            v = _validate_repo_token(str(v), field="target_repo_name")
        setattr(p, k, v)
        p._src[k] = "cli"

    ovs = mapping.get("overrides")
    if not ovs:
        return
    if isinstance(ovs, str):
        ovs = [ovs]
    if not isinstance(ovs, list):
        return
    for item in ovs:
        if not item:
            continue
        k, v = _parse_override_kv(str(item))
        if not hasattr(p, k):
            continue
        cur = getattr(p, k)
        coerced = _coerce_override_value(cur, v)
        if isinstance(cur, list):
            if not isinstance(coerced, list):
                raise RunnerError("CONFIG", "INVALID", f"invalid list override: {coerced!r}")
            should_replace = k in REPO_OWNED_KEYS or k in (
                "self_backup_include_relpaths",
                "target_repo_roots",
            )
            if should_replace:
                setattr(p, k, list(coerced))
            else:
                cur.extend(coerced)
        else:
            if k == "target_repo_name":
                coerced = _validate_repo_token(str(coerced), field="target_repo_name")
            setattr(p, k, coerced)
        p._src[k] = "cli"


def policy_for_log(p: Policy) -> str:
    keys = sorted([k for k in p.__dict__ if k != "_src"])
    lines: list[str] = []
    for k in keys:
        v = getattr(p, k)
        src = p._src.get(k, "unknown")
        lines.append(f"{k}={v!r} (src={src})")
    return "\n".join(lines)
