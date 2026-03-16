from __future__ import annotations

import sys
from pathlib import Path


def _import_am_patch():
    """Import am_patch.* from scripts/ for unit tests.

    This avoids module-level sys.path mutation that triggers lint rules.
    """
    scripts_dir = Path(__file__).parent.parent / "amp"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.cli import parse_args
    from am_patch.config import Policy, apply_cli_overrides, build_policy

    return Policy, apply_cli_overrides, build_policy, parse_args


def test_phase2_cfg_keys_apply() -> None:
    policy_cls, apply_cli_overrides, build_policy, parse_args = _import_am_patch()
    defaults = policy_cls()
    cfg = {
        "patch_dir_name": "patches2",
        "patch_layout_logs_dir": "logs2",
        "lockfile_name": "x.lock",
        "current_log_symlink_enabled": False,
        "log_ts_format": "%Y",
        "log_template_issue": "i_{issue}_{ts}.log",
        "log_template_finalize": "f_{ts}.log",
        "failure_zip_name": "fail.zip",
        "failure_zip_log_dir": "L",
        "failure_zip_patch_dir": "P",
        "workspace_issue_dir_template": "ISSUE_{issue}",
        "workspace_repo_dir_name": "r",
        "workspace_meta_filename": "m.json",
        "workspace_history_logs_dir": "hl",
        "workspace_history_oldlogs_dir": "hol",
        "workspace_history_patches_dir": "hp",
        "workspace_history_oldpatches_dir": "hop",
        "blessed_gate_outputs": ["a/b.xml", "c/d.xml"],
        "scope_ignore_prefixes": [".x/"],
        "scope_ignore_suffixes": [".y"],
        "scope_ignore_contains": ["/z/"],
        "venv_bootstrap_mode": "never",
        "venv_bootstrap_python": ".venv/bin/python3",
        "gate_pytest_py_prefixes": ["badguys", "scripts/am_patch"],
    }
    p = build_policy(defaults, cfg)

    assert p.patch_dir_name == "patches2"
    assert p.patch_layout_logs_dir == "logs2"
    assert p.lockfile_name == "x.lock"
    assert p.current_log_symlink_enabled is False
    assert p.log_ts_format == "%Y"
    assert p.log_template_issue == "i_{issue}_{ts}.log"
    assert p.log_template_finalize == "f_{ts}.log"
    assert p.failure_zip_name == "fail.zip"
    assert p.failure_zip_log_dir == "L"
    assert p.failure_zip_patch_dir == "P"
    assert p.workspace_issue_dir_template == "ISSUE_{issue}"
    assert p.workspace_repo_dir_name == "r"
    assert p.workspace_meta_filename == "m.json"
    assert p.workspace_history_logs_dir == "hl"
    assert p.workspace_history_oldlogs_dir == "hol"
    assert p.workspace_history_patches_dir == "hp"
    assert p.workspace_history_oldpatches_dir == "hop"
    assert p.blessed_gate_outputs == ["a/b.xml", "c/d.xml"]
    assert p.scope_ignore_prefixes == [".x/"]
    assert p.scope_ignore_suffixes == [".y"]
    assert p.scope_ignore_contains == ["/z/"]
    assert p.venv_bootstrap_mode == "never"
    assert p.venv_bootstrap_python == ".venv/bin/python3"
    assert p.gate_pytest_py_prefixes == ["badguys", "scripts/am_patch"]


def test_phase2_cli_flags_set_overrides() -> None:
    policy_cls, apply_cli_overrides, build_policy, parse_args = _import_am_patch()
    # Use a minimal argv to reach parse_args without executing runner.
    cli = parse_args(
        [
            "--patch-dir-name",
            "pp",
            "--patch-layout-logs-dir",
            "ll",
            "--lockfile-name",
            "k.lock",
            "--no-current-log-symlink",
            "--log-ts-format",
            "%Y%m%d",
            "--log-template-issue",
            "x_{issue}_{ts}.log",
            "--log-template-finalize",
            "y_{ts}.log",
            "--failure-zip-name",
            "z.zip",
            "--failure-zip-log-dir",
            "LOGS",
            "--failure-zip-patch-dir",
            "PATCHES",
            "--workspace-issue-dir-template",
            "T_{issue}",
            "--workspace-repo-dir-name",
            "REPO",
            "--workspace-meta-filename",
            "META.json",
            "--workspace-history-logs-dir",
            "A",
            "--workspace-history-oldlogs-dir",
            "B",
            "--workspace-history-patches-dir",
            "C",
            "--workspace-history-oldpatches-dir",
            "D",
            "--blessed-gate-output",
            "one.xml",
            "--blessed-gate-output",
            "two.xml",
            "--scope-ignore-prefix",
            ".am/",
            "--scope-ignore-suffix",
            ".tmp",
            "--scope-ignore-contains",
            "/__X__/",
            "--venv-bootstrap-mode",
            "never",
            "--venv-bootstrap-python",
            ".venv/bin/python",
            "123",
            "patch.py",
        ]
    )

    defaults = policy_cls()
    p = defaults
    apply_cli_overrides(
        p,
        {
            "overrides": cli.overrides,
        },
    )

    assert p.patch_dir_name == "pp"
    assert p.patch_layout_logs_dir == "ll"
    assert p.lockfile_name == "k.lock"
    assert p.current_log_symlink_enabled is False
    assert p.log_ts_format == "%Y%m%d"
    assert p.log_template_issue == "x_{issue}_{ts}.log"
    assert p.log_template_finalize == "y_{ts}.log"
    assert p.failure_zip_name == "z.zip"
    assert p.failure_zip_log_dir == "LOGS"
    assert p.failure_zip_patch_dir == "PATCHES"
    assert p.workspace_issue_dir_template == "T_{issue}"
    assert p.workspace_repo_dir_name == "REPO"
    assert p.workspace_meta_filename == "META.json"
    assert p.workspace_history_logs_dir == "A"
    assert p.workspace_history_oldlogs_dir == "B"
    assert p.workspace_history_patches_dir == "C"
    assert p.workspace_history_oldpatches_dir == "D"
    assert p.blessed_gate_outputs == ["audit/results/pytest_junit.xml", "one.xml", "two.xml"]
    assert ".am/" in p.scope_ignore_prefixes
    assert ".tmp" in p.scope_ignore_suffixes
    assert "/__X__/" in p.scope_ignore_contains
    assert p.venv_bootstrap_mode == "never"
    assert p.venv_bootstrap_python == ".venv/bin/python"


def test_parse_args_workspace_carries_json_out_to_cli_args() -> None:
    _, _, _, parse_args = _import_am_patch()

    cli = parse_args(["--json-out", "123", "msg"])

    assert cli.mode == "workspace"
    assert cli.json_out is True


def test_parse_args_finalize_allows_flags_after_f() -> None:
    _, _, _, parse_args = _import_am_patch()

    cli_before = parse_args(["--skip-docs", "-f", "msg"])
    assert cli_before.mode == "finalize"
    assert cli_before.message == "msg"
    assert cli_before.skip_docs is True

    cli_after = parse_args(["-f", "msg", "--skip-docs"])
    assert cli_after.mode == "finalize"
    assert cli_after.message == "msg"
    assert cli_after.skip_docs is True


def test_parse_args_finalize_still_rejects_positional_args() -> None:
    _, _, _, parse_args = _import_am_patch()

    try:
        parse_args(["-f", "msg", "EXTRA"])
    except SystemExit as e:
        assert "finalize mode" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_failure_zip_template_allows_attempt_without_ts() -> None:
    policy_cls, _, build_policy, _ = _import_am_patch()
    defaults = policy_cls()
    cfg = {
        "failure_zip_template": "patched_issue{issue}_v{attempt:04d}.zip",
    }
    p = build_policy(defaults, cfg)
    assert "{attempt" in p.failure_zip_template


def test_failure_zip_template_rejects_missing_issue() -> None:
    policy_cls, _, build_policy, _ = _import_am_patch()
    defaults = policy_cls()
    cfg = {
        "failure_zip_template": "patched_v{attempt:04d}.zip",
    }
    try:
        build_policy(defaults, cfg)
    except SystemExit:
        raise
    except Exception as e:
        assert "failure_zip_template must contain {issue}" in str(e)
    else:
        raise AssertionError("expected failure")


def test_failure_zip_template_rejects_missing_uniqueness_key() -> None:
    policy_cls, _, build_policy, _ = _import_am_patch()
    defaults = policy_cls()
    cfg = {
        "failure_zip_template": "patched_issue{issue}.zip",
    }
    try:
        build_policy(defaults, cfg)
    except SystemExit:
        raise
    except Exception as e:
        assert "must contain at least one of" in str(e)
    else:
        raise AssertionError("expected failure")


def test_phase2_cli_override_replaces_gate_pytest_py_prefixes() -> None:
    policy_cls, apply_cli_overrides, _build_policy, _parse_args = _import_am_patch()
    p = policy_cls()

    apply_cli_overrides(
        p,
        {
            "overrides": ["gate_pytest_py_prefixes=badguys,scripts/custom"],
        },
    )

    assert p.gate_pytest_py_prefixes == ["badguys", "scripts/custom"]
