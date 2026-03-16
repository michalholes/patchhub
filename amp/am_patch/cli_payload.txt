from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from am_patch.version import RUNNER_VERSION

from .cli_help_text import fmt_full_help, fmt_short_help
from .cli_ipc_surface import add_ipc_override_args


class AppendOverride(argparse.Action):
    """Append KEY=VALUE strings into ns.overrides."""

    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        key: str,
        const_value: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._key = key
        self._const_value = const_value
        super().__init__(option_strings, dest, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        ov = getattr(namespace, "overrides", None)
        if ov is None:
            ov = []
            namespace.overrides = ov
        if values is None or (
            not isinstance(values, str) and isinstance(values, Sequence) and len(values) == 0
        ):
            v = self._const_value if self._const_value is not None else "true"
        elif isinstance(values, str):
            v = values
        else:
            v = ",".join(str(x) for x in values)
        ov.append(f"{self._key}={v}")


@dataclass
class CliArgs:
    mode: str  # workspace|finalize|finalize_workspace
    issue_id: str | None
    patch_script: str | None
    message: str | None

    config_path: str | None

    verbosity: str | None

    log_level: str | None
    json_out: bool | None

    console_color: str | None

    run_all_tests: bool | None
    allow_no_op: bool | None

    compile_check: bool | None
    unified_patch: bool | None
    patch_strip: int | None
    skip_up_to_date: bool | None
    allow_non_main: bool | None

    no_rollback: bool | None

    update_workspace: bool | None
    soft_reset_workspace: bool | None
    enforce_allowed_files: bool | None

    rollback_workspace_on_fail: str | None
    live_repo_guard: bool | None
    live_repo_guard_scope: str | None
    patch_jail: bool | None
    patch_jail_unshare_net: bool | None
    ruff_format: bool | None
    pytest_use_venv: bool | None

    gate_badguys_runner: str | None

    gate_badguys_command: str | None
    gate_badguys_cwd: str | None
    overrides: list[str] | None
    require_push_success: bool | None
    allow_outside_files: bool | None
    allow_declared_untouched: bool | None
    disable_promotion: bool | None
    allow_live_changed: bool | None
    allow_gates_fail: bool | None
    skip_ruff: bool | None
    skip_pytest: bool | None
    skip_mypy: bool | None
    skip_js: bool | None
    skip_docs: bool | None
    skip_monolith: bool | None
    apply_failure_partial_gates_policy: str | None
    apply_failure_zero_gates_policy: str | None
    docs_include: str | None
    docs_exclude: str | None
    gates_order: str | None
    ruff_autofix_legalize_outside: bool | None
    post_success_audit: bool | None
    load_latest_patch: bool | None
    keep_workspace: bool | None
    test_mode: bool | None

    success_archive_name: str | None = None


def _fmt_short_help() -> str:
    return fmt_short_help(RUNNER_VERSION)


def _fmt_full_help() -> str:
    return fmt_full_help(RUNNER_VERSION)


def add_workspace_cmd(subparsers: Any) -> None:
    return


def add_finalize_cmd(subparsers: Any) -> None:
    return


def add_test_cmd(subparsers: Any) -> None:
    return


def add_web_cmd(subparsers: Any) -> None:
    return


def normalize_args(ns: argparse.Namespace) -> argparse.Namespace:
    ns = normalize_args(ns)
    return ns


def parse_args(argv: list[str]) -> CliArgs:
    if "-h" in argv or "--help" in argv:
        print(_fmt_short_help())
        raise SystemExit(0)
    if "-H" in argv or "--help-all" in argv:
        print(_fmt_full_help())
        raise SystemExit(0)

    p = argparse.ArgumentParser(
        prog="am_patch.py",
        description=f"am_patch RUNNER_VERSION={RUNNER_VERSION}",
        add_help=False,
    )
    p.add_argument(
        "--version", action="version", version=f"am_patch RUNNER_VERSION={RUNNER_VERSION}"
    )

    p.add_argument(
        "-a",
        "--allow-undeclared-paths",
        dest="allow_outside_files",
        action="store_true",
        default=None,
    )
    p.add_argument(
        "-t",
        "--allow-untouched-files",
        dest="allow_declared_untouched",
        action="store_true",
        default=None,
    )
    p.add_argument(
        "-l", "--rerun-latest", dest="load_latest_patch", action="store_true", default=None
    )
    p.add_argument("-r", "--run-all-gates", dest="run_all_tests", action="store_true", default=None)
    p.add_argument(
        "-g", "--allow-gates-fail", dest="allow_gates_fail", action="store_true", default=None
    )
    p.add_argument("-o", "--allow-no-op", dest="allow_no_op", action="store_true", default=None)
    p.add_argument("-u", "--unified-patch", dest="unified_patch", action="store_true", default=None)
    p.add_argument("-p", "--patch-strip", dest="patch_strip", metavar="N", type=int, default=None)
    p.add_argument("-c", "--show-config", dest="show_config", action="store_true", default=False)
    p.add_argument(
        "-f", "--finalize-live", dest="finalize_message", metavar="MESSAGE", default=None
    )
    p.add_argument(
        "-w",
        "--finalize-workspace",
        dest="finalize_workspace_issue_id",
        metavar="ISSUE_ID",
        default=None,
    )

    p.add_argument("--config", dest="config_path", metavar="PATH", default=None)
    p.add_argument(
        "--override", dest="overrides", action="append", default=None, metavar="KEY=VALUE"
    )
    p.add_argument(
        "--ruff-mode",
        action=AppendOverride,
        key="gate_ruff_mode",
        dest="overrides",
        choices=("auto", "always"),
    )
    p.add_argument(
        "--mypy-mode",
        action=AppendOverride,
        key="gate_mypy_mode",
        dest="overrides",
        choices=("auto", "always"),
    )
    p.add_argument(
        "--pytest-mode",
        action=AppendOverride,
        key="gate_pytest_mode",
        dest="overrides",
        choices=("auto", "always"),
    )
    p.add_argument(
        "--pytest-routing-mode",
        action=AppendOverride,
        key="pytest_routing_mode",
        dest="overrides",
        choices=("legacy", "bucketed"),
    )
    p.add_argument(
        "--typescript-mode",
        action=AppendOverride,
        key="gate_typescript_mode",
        dest="overrides",
        choices=("auto", "always"),
    )
    p.add_argument(
        "--typescript-targets",
        action=AppendOverride,
        key="typescript_targets",
        dest="overrides",
        metavar="CSV",
    )
    p.add_argument(
        "--typescript-base-tsconfig",
        action=AppendOverride,
        key="gate_typescript_base_tsconfig",
        dest="overrides",
    )

    p.add_argument(
        "--pytest-js-prefixes",
        action=AppendOverride,
        key="gate_pytest_js_prefixes",
        dest="overrides",
        metavar="CSV",
    )

    add_ipc_override_args(p, append_override=AppendOverride)

    p.add_argument(
        "--patch-dir-name", action=AppendOverride, key="patch_dir_name", dest="overrides"
    )
    p.add_argument(
        "--patch-layout-logs-dir",
        action=AppendOverride,
        key="patch_layout_logs_dir",
        dest="overrides",
    )
    p.add_argument(
        "--patch-layout-workspaces-dir",
        action=AppendOverride,
        key="patch_layout_workspaces_dir",
        dest="overrides",
    )
    p.add_argument(
        "--patch-layout-successful-dir",
        action=AppendOverride,
        key="patch_layout_successful_dir",
        dest="overrides",
    )
    p.add_argument(
        "--patch-layout-unsuccessful-dir",
        action=AppendOverride,
        key="patch_layout_unsuccessful_dir",
        dest="overrides",
    )
    p.add_argument("--lockfile-name", action=AppendOverride, key="lockfile_name", dest="overrides")
    p.add_argument(
        "--current-log-symlink-name",
        action=AppendOverride,
        key="current_log_symlink_name",
        dest="overrides",
    )
    p.add_argument(
        "--no-current-log-symlink",
        action=AppendOverride,
        key="current_log_symlink_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    p.add_argument(
        "--current-log-symlink",
        action=AppendOverride,
        key="current_log_symlink_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )

    p.add_argument("--log-ts-format", action=AppendOverride, key="log_ts_format", dest="overrides")
    p.add_argument(
        "--log-template-issue",
        action=AppendOverride,
        key="log_template_issue",
        dest="overrides",
    )
    p.add_argument(
        "--log-template-finalize",
        action=AppendOverride,
        key="log_template_finalize",
        dest="overrides",
    )

    p.add_argument(
        "--failure-zip-name", action=AppendOverride, key="failure_zip_name", dest="overrides"
    )
    p.add_argument(
        "--failure-zip-log-dir",
        action=AppendOverride,
        key="failure_zip_log_dir",
        dest="overrides",
    )
    p.add_argument(
        "--failure-zip-patch-dir",
        action=AppendOverride,
        key="failure_zip_patch_dir",
        dest="overrides",
    )

    p.add_argument(
        "--workspace-issue-dir-template",
        action=AppendOverride,
        key="workspace_issue_dir_template",
        dest="overrides",
    )
    p.add_argument(
        "--workspace-repo-dir-name",
        action=AppendOverride,
        key="workspace_repo_dir_name",
        dest="overrides",
    )
    p.add_argument(
        "--workspace-meta-filename",
        action=AppendOverride,
        key="workspace_meta_filename",
        dest="overrides",
    )

    p.add_argument(
        "--workspace-history-logs-dir",
        action=AppendOverride,
        key="workspace_history_logs_dir",
        dest="overrides",
    )
    p.add_argument(
        "--workspace-history-oldlogs-dir",
        action=AppendOverride,
        key="workspace_history_oldlogs_dir",
        dest="overrides",
    )
    p.add_argument(
        "--workspace-history-patches-dir",
        action=AppendOverride,
        key="workspace_history_patches_dir",
        dest="overrides",
    )
    p.add_argument(
        "--workspace-history-oldpatches-dir",
        action=AppendOverride,
        key="workspace_history_oldpatches_dir",
        dest="overrides",
    )

    p.add_argument(
        "--blessed-gate-output",
        action=AppendOverride,
        key="blessed_gate_outputs",
        dest="overrides",
        help="Append a blessed gate output path (repeatable).",
    )
    p.add_argument(
        "--scope-ignore-prefix",
        action=AppendOverride,
        key="scope_ignore_prefixes",
        dest="overrides",
        help="Append a scope ignore prefix (repeatable).",
    )
    p.add_argument(
        "--scope-ignore-suffix",
        action=AppendOverride,
        key="scope_ignore_suffixes",
        dest="overrides",
        help="Append a scope ignore suffix (repeatable).",
    )
    p.add_argument(
        "--scope-ignore-contains",
        action=AppendOverride,
        key="scope_ignore_contains",
        dest="overrides",
        help="Append a scope ignore substring (repeatable).",
    )

    p.add_argument(
        "--venv-bootstrap-mode",
        action=AppendOverride,
        key="venv_bootstrap_mode",
        dest="overrides",
    )
    p.add_argument(
        "--venv-bootstrap-python",
        action=AppendOverride,
        key="venv_bootstrap_python",
        dest="overrides",
    )
    p.add_argument(
        "--require-push-success", dest="require_push_success", action="store_true", default=None
    )
    p.add_argument(
        "--disable-promotion", dest="disable_promotion", action="store_true", default=None
    )
    p.add_argument(
        "--allow-live-changed", dest="allow_live_changed", action="store_true", default=None
    )
    p.add_argument(
        "--overwrite-live",
        dest="overrides",
        action=AppendOverride,
        key="live_changed_resolution",
        const_value="overwrite_live",
        nargs=0,
    )
    p.add_argument(
        "--overwrite-workspace",
        dest="overrides",
        action=AppendOverride,
        key="live_changed_resolution",
        const_value="overwrite_workspace",
        nargs=0,
    )
    p.add_argument("--keep-workspace", dest="keep_workspace", action="store_true", default=None)
    p.add_argument("--test-mode", dest="test_mode", action="store_true", default=None)
    p.add_argument("--no-compile-check", dest="compile_check", action="store_false", default=None)
    p.add_argument(
        "--success-archive-name",
        dest="success_archive_name",
        default=None,
        help="Success archive zip name template (placeholders: {repo}, {branch}, {issue}, {ts}).",
    )

    p.add_argument(
        "--success-archive-dir",
        dest="overrides",
        action=AppendOverride,
        key="success_archive_dir",
        help="Success archive destination: patch_dir|successful_dir.",
    )
    p.add_argument(
        "--success-archive-cleanup-glob",
        dest="overrides",
        action=AppendOverride,
        key="success_archive_cleanup_glob_template",
        help="Glob template for success archive retention candidate selection.",
    )
    p.add_argument(
        "--success-archive-keep-count",
        dest="overrides",
        action=AppendOverride,
        key="success_archive_keep_count",
        help="Keep the last N success archives matching the glob template (0=disabled).",
    )

    vg = p.add_mutually_exclusive_group()
    vg.add_argument("-q", dest="verbosity", action="store_const", const="quiet", default=None)
    vg.add_argument("-v", dest="verbosity", action="store_const", const="verbose", default=None)
    vg.add_argument("-n", dest="verbosity", action="store_const", const="normal", default=None)
    vg.add_argument("-d", dest="verbosity", action="store_const", const="debug", default=None)
    vg.add_argument(
        "--verbosity",
        dest="verbosity",
        choices=["debug", "verbose", "normal", "warning", "quiet"],
        default=None,
    )

    p.add_argument(
        "--log-level",
        dest="log_level",
        choices=["debug", "verbose", "normal", "warning", "quiet"],
        default=None,
        help="File log level (independent from --verbosity; same semantics).",
    )

    p.add_argument(
        "--json-out",
        dest="json_out",
        action="store_const",
        const=True,
        default=None,
        help="Write a debug-complete NDJSON event log to the JSON logs directory.",
    )

    p.add_argument(
        "--color",
        dest="console_color",
        choices=["auto", "always", "never"],
        default=None,
        help="Console color output mode (auto=TTY only).",
    )
    p.add_argument(
        "--no-color",
        dest="console_color",
        action="store_const",
        const="never",
        default=None,
        help="Disable console color output (same as --color never).",
    )

    p.add_argument("--skip-ruff", dest="skip_ruff", action="store_true", default=None)
    p.add_argument("--skip-pytest", dest="skip_pytest", action="store_true", default=None)
    p.add_argument("--skip-mypy", dest="skip_mypy", action="store_true", default=None)
    p.add_argument("--skip-js", dest="skip_js", action="store_true", default=None)
    p.add_argument("--skip-docs", dest="skip_docs", action="store_true", default=None)
    p.add_argument("--skip-monolith", dest="skip_monolith", action="store_true", default=None)
    p.add_argument("--skip-dont-touch", dest="skip_dont_touch", action="store_true", default=None)

    p.add_argument("--skip-biome", dest="skip_biome", action="store_true", default=None)
    p.add_argument("--skip-typescript", dest="skip_typescript", action="store_true", default=None)

    p.add_argument(
        "--biome-autofix",
        dest="biome_autofix",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--biome-format",
        dest="biome_format",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--biome-autofix-legalize-outside",
        dest="biome_autofix_legalize_outside",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--biome-format-legalize-outside",
        dest="biome_format_legalize_outside",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    p.add_argument(
        "--gate-biome-extensions",
        dest="gate_biome_extensions",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated extensions for biome file-scoped gate.",
    )
    p.add_argument(
        "--gate-biome-command",
        dest="gate_biome_command",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated command tokens for biome gate (Variant B).",
    )
    p.add_argument(
        "--gate-biome-fix-command",
        dest="gate_biome_fix_command",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated command tokens for biome autofix gate (Variant B).",
    )
    p.add_argument(
        "--gate-biome-format-command",
        dest="gate_biome_format_command",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated command tokens for biome format gate (Variant B).",
    )
    p.add_argument(
        "--gate-typescript-extensions",
        dest="gate_typescript_extensions",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated extensions for typescript file-scoped gate.",
    )
    p.add_argument(
        "--gate-typescript-command",
        dest="gate_typescript_command",
        nargs="?",
        const="",
        default=None,
        help="Comma-separated command tokens for typescript gate (Variant B).",
    )

    p.add_argument(
        "--apply-failure-partial-gates-policy",
        dest="apply_failure_partial_gates_policy",
        choices=["never", "always", "repair_only"],
        type=str,
        default=None,
        metavar="{never,always,repair_only}",
    )
    p.add_argument(
        "--apply-failure-zero-gates-policy",
        dest="apply_failure_zero_gates_policy",
        choices=["never", "always", "repair_only"],
        type=str,
        default=None,
        metavar="{never,always,repair_only}",
    )
    p.add_argument("--docs-include", dest="docs_include", nargs="?", const="", default=None)
    p.add_argument("--docs-exclude", dest="docs_exclude", nargs="?", const="", default=None)
    p.add_argument("--gates-order", dest="gates_order", nargs="?", const="", default=None)

    p.add_argument(
        "--ruff-autofix-legalize-outside",
        dest="ruff_autofix_legalize_outside",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    p.add_argument(
        "--rollback-workspace-on-fail",
        dest="rollback_workspace_on_fail",
        nargs="?",
        const="none-applied",
        choices=["none-applied", "always", "never"],
        default=None,
        metavar="{none-applied,always,never}",
    )

    p.add_argument(
        "--no-rollback-workspace-on-fail",
        dest="rollback_workspace_on_fail",
        action="store_const",
        const="never",
        default=None,
    )
    p.add_argument(
        "--live-repo-guard",
        dest="live_repo_guard",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--live-repo-guard-scope",
        dest="live_repo_guard_scope",
        choices=["patch", "patch_and_gates"],
        default=None,
    )
    p.add_argument(
        "--patch-jail", dest="patch_jail", action=argparse.BooleanOptionalAction, default=None
    )
    p.add_argument(
        "--patch-jail-unshare-net",
        dest="patch_jail_unshare_net",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--ruff-format", dest="ruff_format", action=argparse.BooleanOptionalAction, default=None
    )
    p.add_argument(
        "--pytest-use-venv",
        dest="pytest_use_venv",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    p.add_argument(
        "--gate-badguys-runner",
        dest="gate_badguys_runner",
        choices=["auto", "on", "off"],
        default=None,
        help="Runner-only extra gate: badguys/badguys.py -q (auto=only on runner changes).",
    )

    p.add_argument(
        "--gate-badguys-command",
        dest="gate_badguys_command",
        default=None,
        help=(
            "BADGUYS gate command (argv string; parsed like shell). "
            "Default: 'badguys/badguys.py -q'."
        ),
    )
    p.add_argument(
        "--gate-badguys-cwd",
        dest="gate_badguys_cwd",
        choices=["auto", "workspace", "clone", "live"],
        default=None,
        help="Where to run BADGUYS gate: auto|workspace|clone|live.",
    )

    p.add_argument(
        "--post-success-audit",
        dest="post_success_audit",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    p.add_argument("--skip-up-to-date", dest="skip_up_to_date", action="store_true", default=None)
    p.add_argument("--allow-non-main", dest="allow_non_main", action="store_true", default=None)
    p.add_argument("--update-workspace", dest="update_workspace", action="store_true", default=None)
    p.add_argument(
        "--soft-reset-workspace", dest="soft_reset_workspace", action="store_true", default=None
    )
    p.add_argument(
        "--enforce-allowed-files", dest="enforce_allowed_files", action="store_true", default=None
    )

    p.add_argument(
        "--no-rollback-on-commit-push-failure",
        dest="no_rollback",
        action="store_true",
        default=None,
    )

    p.add_argument("rest", nargs="*")
    ns = p.parse_args(argv)

    if ns.overrides is not None:
        norm: list[str] = []
        for item in ns.overrides:
            if "=" in str(item):
                k, v = str(item).split("=", 1)
                norm.append(f"{k.strip().lower()}={v}")
            else:
                norm.append(str(item))
        ns.overrides = norm

    # Map explicit gate flags into overrides so engine.py does not need changes.
    # Precedence: CLI flags > config > defaults (apply_cli_overrides marks these as src=cli).
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
        v = "true" if bool(ns.biome_autofix) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_autofix={v}"]
    if getattr(ns, "biome_format", None) is not None:
        v = "true" if bool(ns.biome_format) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_format={v}"]
    if getattr(ns, "biome_autofix_legalize_outside", None) is not None:
        v = "true" if bool(ns.biome_autofix_legalize_outside) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_autofix_legalize_outside={v}"]
    if getattr(ns, "biome_format_legalize_outside", None) is not None:
        v = "true" if bool(ns.biome_format_legalize_outside) else "false"
        ns.overrides = (ns.overrides or []) + [f"biome_format_legalize_outside={v}"]
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

    if ns.show_config:
        return CliArgs(
            mode="show_config",
            issue_id=None,
            patch_script=None,
            message=None,
            config_path=ns.config_path,
            verbosity=ns.verbosity,
            log_level=getattr(ns, "log_level", None),
            json_out=getattr(ns, "json_out", None),
            console_color=getattr(ns, "console_color", None),
            run_all_tests=ns.run_all_tests,
            allow_no_op=ns.allow_no_op,
            compile_check=getattr(ns, "compile_check", None),
            unified_patch=getattr(ns, "unified_patch", None),
            patch_strip=getattr(ns, "patch_strip", None),
            skip_up_to_date=ns.skip_up_to_date,
            allow_non_main=ns.allow_non_main,
            no_rollback=ns.no_rollback,
            update_workspace=ns.update_workspace,
            soft_reset_workspace=ns.soft_reset_workspace,
            enforce_allowed_files=ns.enforce_allowed_files,
            rollback_workspace_on_fail=ns.rollback_workspace_on_fail,
            live_repo_guard=ns.live_repo_guard,
            live_repo_guard_scope=ns.live_repo_guard_scope,
            patch_jail=ns.patch_jail,
            patch_jail_unshare_net=ns.patch_jail_unshare_net,
            ruff_format=ns.ruff_format,
            pytest_use_venv=ns.pytest_use_venv,
            gate_badguys_runner=getattr(ns, "gate_badguys_runner", None),
            gate_badguys_command=getattr(ns, "gate_badguys_command", None),
            gate_badguys_cwd=getattr(ns, "gate_badguys_cwd", None),
            overrides=ns.overrides,
            require_push_success=ns.require_push_success,
            allow_outside_files=ns.allow_outside_files,
            allow_declared_untouched=ns.allow_declared_untouched,
            disable_promotion=ns.disable_promotion,
            allow_live_changed=ns.allow_live_changed,
            allow_gates_fail=ns.allow_gates_fail,
            skip_ruff=ns.skip_ruff,
            skip_pytest=ns.skip_pytest,
            skip_mypy=ns.skip_mypy,
            skip_js=getattr(ns, "skip_js", None),
            skip_docs=getattr(ns, "skip_docs", None),
            skip_monolith=getattr(ns, "skip_monolith", None),
            apply_failure_partial_gates_policy=getattr(
                ns, "apply_failure_partial_gates_policy", None
            ),
            apply_failure_zero_gates_policy=getattr(ns, "apply_failure_zero_gates_policy", None),
            docs_include=getattr(ns, "docs_include", None),
            docs_exclude=getattr(ns, "docs_exclude", None),
            gates_order=ns.gates_order,
            ruff_autofix_legalize_outside=ns.ruff_autofix_legalize_outside,
            load_latest_patch=ns.load_latest_patch,
            keep_workspace=ns.keep_workspace,
            test_mode=ns.test_mode,
            success_archive_name=getattr(ns, "success_archive_name", None),
            post_success_audit=ns.post_success_audit,
        )

    if ns.finalize_workspace_issue_id is not None:
        mode = "finalize_workspace"
        issue_id = str(ns.finalize_workspace_issue_id)
        if not issue_id.isdigit():
            raise SystemExit("ISSUE_ID must be numeric")
        patch_script = None
        message = None
        if ns.finalize_message is not None:
            raise SystemExit(
                "finalize-workspace mode must not use -f/--finalize-live; "
                "commit message is read from workspace meta.json"
            )
        if ns.rest:
            raise SystemExit("finalize-workspace mode must not include positional args")
    elif ns.finalize_message is not None:
        mode = "finalize"
        issue_id = None
        patch_script = None
        message = ns.finalize_message
        if ns.rest:
            raise SystemExit("finalize mode (-f/--finalize-live) must not include positional args")
    else:
        mode = "workspace"
        if len(ns.rest) < 2:
            raise SystemExit("workspace mode requires: ISSUE_ID MESSAGE [PATCH_SCRIPT]")
        issue_id = ns.rest[0]
        if not str(issue_id).isdigit():
            raise SystemExit("ISSUE_ID must be numeric")
        message = ns.rest[1]
        patch_script = ns.rest[2] if len(ns.rest) >= 3 else None

    return CliArgs(
        mode=mode,
        issue_id=issue_id,
        patch_script=patch_script,
        message=message,
        config_path=ns.config_path,
        verbosity=ns.verbosity,
        log_level=getattr(ns, "log_level", None),
        json_out=getattr(ns, "json_out", None),
        console_color=getattr(ns, "console_color", None),
        run_all_tests=ns.run_all_tests,
        allow_no_op=ns.allow_no_op,
        compile_check=getattr(ns, "compile_check", None),
        unified_patch=getattr(ns, "unified_patch", None),
        patch_strip=getattr(ns, "patch_strip", None),
        skip_up_to_date=ns.skip_up_to_date,
        allow_non_main=ns.allow_non_main,
        no_rollback=ns.no_rollback,
        update_workspace=ns.update_workspace,
        soft_reset_workspace=ns.soft_reset_workspace,
        enforce_allowed_files=ns.enforce_allowed_files,
        rollback_workspace_on_fail=ns.rollback_workspace_on_fail,
        live_repo_guard=ns.live_repo_guard,
        live_repo_guard_scope=ns.live_repo_guard_scope,
        patch_jail=ns.patch_jail,
        patch_jail_unshare_net=ns.patch_jail_unshare_net,
        ruff_format=ns.ruff_format,
        pytest_use_venv=ns.pytest_use_venv,
        gate_badguys_runner=ns.gate_badguys_runner,
        gate_badguys_command=getattr(ns, "gate_badguys_command", None),
        gate_badguys_cwd=getattr(ns, "gate_badguys_cwd", None),
        overrides=ns.overrides,
        require_push_success=ns.require_push_success,
        allow_outside_files=ns.allow_outside_files,
        allow_declared_untouched=ns.allow_declared_untouched,
        disable_promotion=ns.disable_promotion,
        allow_live_changed=ns.allow_live_changed,
        allow_gates_fail=ns.allow_gates_fail,
        skip_ruff=ns.skip_ruff,
        skip_pytest=ns.skip_pytest,
        skip_mypy=ns.skip_mypy,
        skip_js=getattr(ns, "skip_js", None),
        skip_docs=getattr(ns, "skip_docs", None),
        skip_monolith=getattr(ns, "skip_monolith", None),
        apply_failure_partial_gates_policy=getattr(ns, "apply_failure_partial_gates_policy", None),
        apply_failure_zero_gates_policy=getattr(ns, "apply_failure_zero_gates_policy", None),
        docs_include=getattr(ns, "docs_include", None),
        docs_exclude=getattr(ns, "docs_exclude", None),
        gates_order=ns.gates_order,
        ruff_autofix_legalize_outside=ns.ruff_autofix_legalize_outside,
        load_latest_patch=ns.load_latest_patch,
        keep_workspace=ns.keep_workspace,
        test_mode=ns.test_mode,
        post_success_audit=ns.post_success_audit,
    )
