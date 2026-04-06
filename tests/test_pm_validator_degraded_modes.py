from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from governance.pm_validator_runtime_support import build_validation_context
except ModuleNotFoundError as exc:
    pytest.skip(f"missing isolated dependency: {exc.name}", allow_module_level=True)


def _base():
    module_path = REPO_ROOT / "tests" / "test_pm_validator.py"
    spec = importlib.util.spec_from_file_location("issue443_base_test_pm_validator", module_path)
    assert spec is not None and spec.loader is not None
    base_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base_module)
    return base_module


def test_initial_context_uses_full_snapshot_tree() -> None:
    snapshot_files = {
        "scripts/sample.py": b"def value():\n    return 1\n",
        "scripts/other.py": b"VALUE = 2\n",
    }
    ctx = build_validation_context(
        decision_paths=["scripts/sample.py"],
        patch_members=[],
        snapshot_files=snapshot_files,
        overlay_files=None,
        supplemental_files=[],
    )
    assert ctx.mode == "initial"
    assert ctx.runnable_paths == ["scripts/sample.py"]
    assert ctx.baseline_files == snapshot_files


def test_repair_overlay_only_partitions_paths_and_emits_degraded_rules() -> None:
    overlay_files = {"scripts/sample.py": b"def value():\n    return 2\n"}
    ctx = build_validation_context(
        decision_paths=["scripts/sample.py", "tests/test_sample.txt"],
        patch_members=[],
        snapshot_files=None,
        overlay_files=overlay_files,
        supplemental_files=[],
    )
    assert ctx.mode == "repair-overlay-only"
    assert ctx.runnable_paths == ["scripts/sample.py"]
    assert ctx.baseline_files == overlay_files
    verdicts = {(item.rule_id, item.status, item.detail) for item in ctx.degraded_rules}
    assert (
        "REPAIR_OVERLAY_UNCOVERED:tests/test_sample.txt",
        "SKIP",
        "missing_pre_patch_baseline_in_repair_overlay",
    ) in verdicts
    assert (
        "REPAIR_TARGET_SNAPSHOT_CONSISTENCY",
        "SKIP",
        "workspace_snapshot_absent",
    ) in verdicts
    assert ("REPAIR_SUPPLEMENTAL_AUTHORITY", "SKIP", "workspace_snapshot_absent") in verdicts


def test_member_local_failures_are_aggregated_before_abort(tmp_path: Path) -> None:
    base = _base()
    snapshot = tmp_path / f"{base.DEFAULT_TARGET}-main_666.zip"
    instructions_zip = base._instructions_zip(tmp_path / "instructions.zip")
    patch_zip = tmp_path / "issue_601_v2.zip"
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    base._snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    long_line = "X" * 101
    base._write_zip(
        patch_zip,
        {
            "COMMIT_MESSAGE.txt": (base.COMMIT + "\n").encode("utf-8"),
            "ISSUE_NUMBER.txt": b"601\n",
            "target.txt": (base.DEFAULT_TARGET + "\n").encode("utf-8"),
            "patches/per_file/invalid/name.patch": b"diff --git a/x b/x\n--- a/x\n+++ b/x\n",
            base._safe_member(relpath): base._added_patch(relpath, long_line + "\n"),
        },
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(base.SCRIPT),
            "601",
            base.COMMIT,
            str(patch_zip),
            str(instructions_zip),
            "--workspace-snapshot",
            str(snapshot),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert (
        "RULE PATCH_MEMBER_PATHS: FAIL - "
        "invalid_member:patches/per_file/invalid/name.patch" in proc.stdout
    )
    assert (
        "RULE LINE_LENGTH: FAIL - "
        "patches/per_file/scripts__sample.py.patch:added_line_too_long" in proc.stdout
    )


def test_apply_failure_emits_explicit_not_runnable_verdicts(tmp_path: Path) -> None:
    base = _base()
    snapshot = tmp_path / f"{base.DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = base._instructions_zip(tmp_path / "instructions.zip")
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    bad_old = "def value():\n    return 9\n"
    after = "def value():\n    return 2\n"
    base._snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    base._patch_zip(
        patch_zip,
        {base._safe_member(relpath): base._git_patch(relpath, bad_old, after)},
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(base.SCRIPT),
            "601",
            base.COMMIT,
            str(patch_zip),
            str(instructions_zip),
            "--workspace-snapshot",
            str(snapshot),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "RULE GIT_APPLY_CHECK:patches/per_file/scripts__sample.py.patch: FAIL" in proc.stdout
    assert "RULE PY_COMPILE: SKIP - apply_check_failed" in proc.stdout
    assert "RULE MONOLITH: SKIP - apply_check_failed" in proc.stdout
    assert "RULE EXTERNAL_GATE:RUFF: SKIP - apply_check_failed" in proc.stdout


def test_rc_resolver_emits_explicit_degraded_outcome_when_repo_spec_missing(tmp_path: Path) -> None:
    base = _base()
    snapshot = tmp_path / f"{base.DEFAULT_TARGET}-main_666.zip"
    with ZipFile(snapshot, "w") as zf:
        zf.writestr("governance/governance.jsonl", base._governance_bytes())
        zf.writestr("scripts/sample.py", b"def value():\n    return 1\n")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "governance.rc_resolver",
            "scripts/sample.py::value",
            "--workspace-snapshot",
            str(snapshot),
            "--spec",
            "governance/specification.jsonl",
            "--handoff-output",
            str(tmp_path / "HANDOFF.md"),
            "--pack-output",
            str(tmp_path / "constraint_pack.json"),
            "--hash-output",
            str(tmp_path / "hash_pack.txt"),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "RULE RESOLVER: SKIP - missing_repo_specification_jsonl" in proc.stdout
