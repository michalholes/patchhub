from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from governance import rc_resolver
    from governance.pm_validator import AUTHORITY_ONLY_PATHS
    from governance.rc_resolver import build_pack as build_resolver_pack
    from governance.workflow_effective_context import build_workflow_effective_context
except ModuleNotFoundError as exc:
    pytest.skip(
        f"missing isolated dependency: {exc.name}",
        allow_module_level=True,
    )

SCRIPT = Path(__file__).resolve().parents[1] / "governance/pm_validator.py"
COMMIT = "Align PM validator monolith checks"
DEFAULT_TARGET = "audiomason2"
ALT_TARGET = "patchhub"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git_patch(relpath: str, old_text: str | None, new_text: str | None) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        old = root / "old" / relpath
        new = root / "new" / relpath
        if old_text is not None:
            _write(old, old_text)
        else:
            old.parent.mkdir(parents=True, exist_ok=True)
        if new_text is not None:
            _write(new, new_text)
        else:
            new.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                str(old.relative_to(root)),
                str(new.relative_to(root)),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, proc.stderr
        patch = proc.stdout.replace(f"a/old/{relpath}", f"a/{relpath}")
        patch = patch.replace(f"b/new/{relpath}", f"b/{relpath}")
        return patch.encode("utf-8")


def _safe_member(relpath: str) -> str:
    return "patches/per_file/" + relpath.replace("/", "__") + ".patch"


def _added_patch(relpath: str, new_text: str) -> bytes:
    added_lines = new_text.splitlines()
    hunk = "".join(f"+{line}\n" for line in added_lines)
    return (
        f"diff --git a/{relpath} b/{relpath}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{relpath}\n"
        f"@@ -0,0 +1,{len(added_lines)} @@\n"
        f"{hunk}"
    ).encode()


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _governance_bytes() -> bytes:
    return (Path(__file__).resolve().parents[1] / "governance/governance.jsonl").read_bytes()


def _authority_bytes(source_path: str) -> bytes:
    if source_path == "governance/governance.jsonl":
        return _governance_bytes()
    if source_path == "governance/specification.jsonl":
        return _spec_bytes()
    raise AssertionError(source_path)


def _spec_bytes() -> bytes:
    objects = [
        {"type": "meta", "id": "meta-1"},
        {"type": "binding_meta", "id": "binding-meta-1"},
        {"type": "oracle", "id": "oracle-1"},
        {
            "type": "obligation_binding",
            "id": "pack-rule-1",
            "binding_type": "constraint_pack",
            "match": {"phase": "final", "target": "implementation_scope"},
            "symbol_role": "constraint_pack",
            "authoritative_semantics": "constraint pack enforcement",
            "peer_renderers": [],
            "shared_contract_refs": [],
            "downstream_consumers": [],
            "exception_state_refs": [],
            "required_wiring": [],
            "forbidden": [],
            "required_validation": [],
            "verification_mode": "machine",
            "verification_method": "validator",
            "semantic_group": "constraint_pack",
            "conflict_policy": "fail_closed",
            "oracle_ref": "oracle-1",
        },
    ]
    payload = "\n".join(json.dumps(obj, sort_keys=True, ensure_ascii=True) for obj in objects)
    return (payload + "\n").encode("utf-8")


def _pack_bytes(
    spec_raw: bytes,
    *,
    mode: str = "final",
    scope: str = "implementation_scope",
    source_path: str = "governance/governance.jsonl",
) -> bytes:
    active_binding = {
        "type": "obligation_binding",
        "id": "pack-rule-1",
        "binding_type": "constraint_pack",
        "match": {"phase": "final", "target": "implementation_scope"},
        "symbol_role": "constraint_pack",
        "authoritative_semantics": "constraint pack enforcement",
        "peer_renderers": [],
        "shared_contract_refs": [],
        "downstream_consumers": [],
        "exception_state_refs": [],
        "required_wiring": [],
        "forbidden": [],
        "required_validation": [],
        "verification_mode": "machine",
        "verification_method": "validator",
        "semantic_group": "constraint_pack",
        "conflict_policy": "fail_closed",
        "oracle_ref": "oracle-1",
    }
    pack = {
        "target_symbol": None,
        "target_scope": scope,
        "mode": mode,
        "spec_fingerprint": hashlib.sha256(spec_raw).hexdigest(),
        "binding_meta_id": "binding-meta-1",
        "active_bindings": [active_binding],
        "active_rule_ids": ["pack-rule-1"],
        "full_rule_text": {"pack-rule-1": "constraint pack enforcement"},
        "match_basis": {"pack-rule-1": {"phase": "final", "target": "implementation_scope"}},
        "authoritative_sources": [source_path],
        "shared_contracts": [],
        "downstream_consumers": [],
        "exception_state_refs": [],
        "required_wiring": [],
        "forbidden_strategies": [],
        "required_validation": [],
        "verification_mode_per_rule": {"pack-rule-1": "machine"},
        "verification_method_per_rule": {"pack-rule-1": "validator"},
        "oracle_refs": {"pack-rule-1": "oracle-1"},
        "aggregate_scope_metadata": {
            "binding_count": 1,
            "mode": mode,
            "target_scope": scope,
        },
    }
    return (json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _instructions_zip(
    path: Path,
    *,
    mode: str = "final",
    scope: str = "implementation_scope",
    source_path: str = "governance/governance.jsonl",
) -> Path:
    spec_raw = _authority_bytes(source_path)
    governance_workflow_raw = None
    if scope == "implementation_scope" and source_path != "governance/governance.jsonl":
        governance_workflow_raw = _governance_bytes()
    pack_raw = build_resolver_pack(
        spec_raw,
        mode,
        scope,
        spec_path=source_path,
        governance_workflow_raw=governance_workflow_raw,
    )
    _write_zip(
        path,
        {
            "HANDOFF.md": b"SPEC CONTEXT\nPM version used: resolver-generated\n",
            "constraint_pack.json": pack_raw,
            "hash_pack.txt": (hashlib.sha256(pack_raw).hexdigest() + "\n").encode("ascii"),
        },
    )
    return path


def _with_spec(
    members: dict[str, bytes],
    *,
    source_path: str = "governance/governance.jsonl",
) -> dict[str, bytes]:
    out = dict(members)
    out.setdefault("governance/governance.jsonl", _governance_bytes())
    out.setdefault("governance/specification.jsonl", _spec_bytes())
    out.setdefault(source_path, _authority_bytes(source_path))
    return out


def _patch_zip(
    path: Path,
    members: dict[str, bytes],
    *,
    issue: str = "601",
    target: str | None = DEFAULT_TARGET,
) -> None:
    files = {
        "COMMIT_MESSAGE.txt": (COMMIT + "\n").encode("utf-8"),
        "ISSUE_NUMBER.txt": (issue + "\n").encode("utf-8"),
        **members,
    }
    if target is not None:
        files["target.txt"] = (target + "\n").encode("utf-8")
    _write_zip(path, files)


def _overlay_zip(
    path: Path,
    members: dict[str, bytes],
    *,
    target: str = DEFAULT_TARGET,
) -> None:
    _write_zip(path, {**_with_spec(members), "target.txt": (target + "\n").encode("utf-8")})


def _snapshot_zip(path: Path, members: dict[str, bytes]) -> None:
    _write_zip(path, _with_spec(members))


def _run(instructions_zip: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, str(instructions_zip)],
        capture_output=True,
        text=True,
        check=False,
    )


def _module_text(*, exports: int, values: int) -> str:
    lines: list[str] = []
    for idx in range(1, exports + 1):
        lines.extend(
            [
                f"def export_{idx}() -> int:",
                f"    return {idx}",
                "",
            ]
        )
    for idx in range(1, values + 1):
        lines.append(f"VALUE_{idx} = {idx}")
    lines.append("")
    return "\n".join(lines)


def test_initial_mode_passes(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout
    assert "RULE MONOLITH: PASS" in proc.stdout
    assert "RULE PACK_RECOMPUTE: PASS - recompute_match" in proc.stdout


def test_initial_mode_passes_with_target_file(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"RULE TARGET_FILE: PASS - {DEFAULT_TARGET}" in proc.stdout


def test_initial_mode_without_target_file_fails(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
        target=None,
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE TARGET_FILE: FAIL - missing_target_file" in proc.stdout


def test_initial_mode_rejects_invalid_snapshot_basename(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / "workspace.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert (
        "RULE INITIAL_TARGET_SOURCE: FAIL - "
        "invalid_workspace_snapshot_basename:workspace.zip" in proc.stdout
    )


def test_initial_mode_rejects_target_mismatch(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{ALT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert (
        f"RULE INITIAL_TARGET_MATCH: FAIL - expected={ALT_TARGET}:actual={DEFAULT_TARGET}"
        in proc.stdout
    )


def test_target_file_rejects_crlf_newlines(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _write_zip(
        patch_zip,
        {
            "COMMIT_MESSAGE.txt": (COMMIT + "\n").encode("utf-8"),
            "ISSUE_NUMBER.txt": b"601\n",
            "target.txt": (DEFAULT_TARGET + "\r\n").encode("utf-8"),
            _safe_member(relpath): _git_patch(relpath, before, after),
        },
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE TARGET_FILE: FAIL - target_must_use_lf_newlines" in proc.stdout


def test_target_file_rejects_multiple_lines(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _write_zip(
        patch_zip,
        {
            "COMMIT_MESSAGE.txt": (COMMIT + "\n").encode("utf-8"),
            "ISSUE_NUMBER.txt": b"601\n",
            "target.txt": f"{DEFAULT_TARGET}\nextra\n".encode(),
            _safe_member(relpath): _git_patch(relpath, before, after),
        },
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE TARGET_FILE: FAIL - target_must_have_exactly_one_line" in proc.stdout


def test_repair_overlay_only_passes(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 2\n"
    after = "def value():\n    return 3\n"
    overlay = tmp_path / "patched_issue601_v1.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _overlay_zip(overlay, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--repair-overlay",
        str(overlay),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout
    assert "RULE GIT_APPLY_CHECK:patches/per_file/scripts__sample.py.patch: PASS" in proc.stdout


def test_repair_supplemental_file_is_supported(tmp_path: Path) -> None:
    relpath = "tests/test_sample.txt"
    before = "a\n"
    after = "b\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    overlay = tmp_path / "patched_issue601_v1.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _overlay_zip(overlay, {"scripts/sample.py": b"def value():\n    return 2\n"})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--repair-overlay",
        str(overlay),
        "--workspace-snapshot",
        str(snapshot),
        "--supplemental-file",
        relpath,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout


def test_repair_without_required_supplemental_file_fails(tmp_path: Path) -> None:
    relpath = "tests/test_sample.txt"
    before = "a\n"
    after = "b\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    overlay = tmp_path / "patched_issue601_v1.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _overlay_zip(overlay, {})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--repair-overlay",
        str(overlay),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    expected = (
        "RULE VALIDATION_ERROR: FAIL - repair_requires_supplemental_file:['tests/test_sample.txt']"
    )
    assert expected in proc.stdout


def test_repair_rejects_target_mismatch(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 2\n"
    after = "def value():\n    return 3\n"
    overlay = tmp_path / "patched_issue601_v1.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _overlay_zip(overlay, {relpath: before.encode("utf-8")}, target=ALT_TARGET)
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--repair-overlay",
        str(overlay),
    )
    assert proc.returncode == 1
    assert (
        f"RULE REPAIR_TARGET_MATCH: FAIL - expected={ALT_TARGET}:actual={DEFAULT_TARGET}"
        in proc.stdout
    )


def test_repair_rejects_overlay_snapshot_target_mismatch(tmp_path: Path) -> None:
    relpath = "tests/test_sample.txt"
    before = "a\n"
    after = "b\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    overlay = tmp_path / "patched_issue601_v1.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _overlay_zip(overlay, {}, target=ALT_TARGET)
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
        target=ALT_TARGET,
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--repair-overlay",
        str(overlay),
        "--workspace-snapshot",
        str(snapshot),
        "--supplemental-file",
        relpath,
    )
    assert proc.returncode == 1
    assert (
        f"RULE REPAIR_TARGET_SNAPSHOT_CONSISTENCY: FAIL - "
        f"overlay={ALT_TARGET}:snapshot={DEFAULT_TARGET}" in proc.stdout
    )


def test_monolith_hub_growth_is_reported(tmp_path: Path) -> None:
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    base_files = {
        "scripts/am_patch/importer_a.py": "def run() -> None:\n    return None\n",
        "scripts/am_patch/importer_b.py": "def run() -> None:\n    return None\n",
        "scripts/am_patch/importer_c.py": "def run() -> None:\n    return None\n",
        "tests/test_importer_a.py": "def test_a() -> None:\n    return None\n",
        "tests/test_importer_b.py": "def test_b() -> None:\n    return None\n",
    }
    _snapshot_zip(snapshot, {path: text.encode("utf-8") for path, text in base_files.items()})

    hub_body = "\n".join(
        [
            "def alpha() -> int:",
            "    return 1",
            "",
            "def beta() -> int:",
            "    return 2",
            "",
            "def gamma() -> int:",
            "    return 3",
            "",
            *[f"VALUE_{idx} = {idx}" for idx in range(1, 105)],
            "",
        ]
    )
    members = {
        _safe_member("scripts/am_patch/hub.py"): _added_patch(
            "scripts/am_patch/hub.py",
            hub_body,
        ),
        _safe_member("scripts/am_patch/importer_a.py"): _git_patch(
            "scripts/am_patch/importer_a.py",
            base_files["scripts/am_patch/importer_a.py"],
            "from am_patch.hub import alpha\n\n\ndef run() -> None:\n    alpha()\n",
        ),
        _safe_member("scripts/am_patch/importer_b.py"): _git_patch(
            "scripts/am_patch/importer_b.py",
            base_files["scripts/am_patch/importer_b.py"],
            "from am_patch.hub import beta\n\n\ndef run() -> None:\n    beta()\n",
        ),
        _safe_member("scripts/am_patch/importer_c.py"): _git_patch(
            "scripts/am_patch/importer_c.py",
            base_files["scripts/am_patch/importer_c.py"],
            "from am_patch.hub import gamma\n\n\ndef run() -> None:\n    gamma()\n",
        ),
        _safe_member("tests/test_importer_a.py"): _git_patch(
            "tests/test_importer_a.py",
            base_files["tests/test_importer_a.py"],
            "from am_patch.hub import alpha\n\n\ndef test_a() -> None:\n    assert alpha() == 1\n",
        ),
        _safe_member("tests/test_importer_b.py"): _git_patch(
            "tests/test_importer_b.py",
            base_files["tests/test_importer_b.py"],
            "from am_patch.hub import beta\n\n\ndef test_b() -> None:\n    assert beta() == 2\n",
        ),
    }
    _patch_zip(patch_zip, members)

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE MONOLITH: FAIL" in proc.stdout
    assert "hub_signal_fanin:scripts/am_patch/hub.py" in proc.stdout


def test_initial_mode_fails_on_non_ascii_commit_message(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _write_zip(
        patch_zip,
        {
            "COMMIT_MESSAGE.txt": ("Align PM validator monolith checks e\u0301\n".encode()),
            "ISSUE_NUMBER.txt": b"601\n",
            "target.txt": (DEFAULT_TARGET + "\n").encode("utf-8"),
            _safe_member(relpath): _git_patch(relpath, before, after),
        },
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE COMMIT_MESSAGE_FILE: FAIL - missing_or_non_ascii_commit_message" in proc.stdout


def test_initial_mode_fails_on_non_ascii_patch_text(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = 'def value():\n    return "e\u0301"\n'
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE PATCH_ASCII: FAIL" in proc.stdout
    assert "non_ascii_patch_text" in proc.stdout


def test_initial_mode_fails_on_non_ascii_patch_member_path(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: b"def value():\n    return 1\n"})
    _patch_zip(
        patch_zip,
        {
            "patches/per_file/scripts__na\u00efve.py.patch": _added_patch(
                relpath,
                "def value():\n    return 2\n",
            )
        },
    )

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE PATCH_MEMBER_PATHS: FAIL - non_ascii_member:" in proc.stdout


def test_monolith_threshold_crossing_to_large_fails(tmp_path: Path) -> None:
    relpath = "scripts/threshold_large.py"
    before = _module_text(exports=10, values=633)
    after = _module_text(exports=13, values=987)
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE MONOLITH: FAIL" in proc.stdout
    assert "large_file_growth:scripts/threshold_large.py" in proc.stdout


def test_monolith_threshold_crossing_to_large_within_allowance_passes(
    tmp_path: Path,
) -> None:
    relpath = "scripts/threshold_large.py"
    before = _module_text(exports=10, values=878)
    after = _module_text(exports=12, values=880)
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout
    assert "RULE MONOLITH: PASS" in proc.stdout


def test_monolith_threshold_crossing_to_huge_fails_on_growth(tmp_path: Path) -> None:
    relpath = "scripts/threshold_huge.py"
    before = _module_text(exports=10, values=1279)
    after = _module_text(exports=10, values=1280)
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE MONOLITH: FAIL" in proc.stdout
    assert "huge_file_growth:scripts/threshold_huge.py" in proc.stdout


def test_monolith_drop_below_large_threshold_passes(tmp_path: Path) -> None:
    relpath = "scripts/threshold_drop.py"
    before = _module_text(exports=10, values=880)
    after = _module_text(exports=12, values=872)
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout
    assert "RULE MONOLITH: PASS" in proc.stdout


def test_initial_mode_rejects_unexpected_root_entry(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})
    with ZipFile(patch_zip, "a", compression=ZIP_DEFLATED) as zf:
        zf.writestr("notes.txt", b"x\n")

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert f"RULE TARGET_FILE: PASS - {DEFAULT_TARGET}" in proc.stdout
    assert "RULE PER_FILE_LAYOUT: FAIL - extra_entries=['notes.txt']" in proc.stdout


def test_authority_only_paths_are_corpus_only() -> None:
    assert {
        "governance/governance.jsonl",
        "governance/specification.jsonl",
    } == AUTHORITY_ONLY_PATHS


def test_resolver_reuses_canonical_workflow_effective_context() -> None:
    assert build_resolver_pack.__module__ == "governance.rc_resolver"
    assert build_workflow_effective_context.__module__ == ("governance.workflow_effective_context")
    assert rc_resolver.build_workflow_effective_context is (build_workflow_effective_context)


def test_initial_mode_passes_with_specification_authority_source(tmp_path: Path) -> None:
    relpath = "governance/rc_resolver.py"
    before = "VALUE = 1\n"
    after = "VALUE = 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_777.zip"
    patch_zip = tmp_path / "issue_602_v1.zip"
    instructions_zip = _instructions_zip(
        tmp_path / "instructions_gov.zip",
        source_path="governance/specification.jsonl",
    )
    _snapshot_zip(
        snapshot,
        _with_spec(
            {relpath: before.encode("utf-8")},
            source_path="governance/specification.jsonl",
        ),
    )
    _patch_zip(
        patch_zip,
        {_safe_member(relpath): _git_patch(relpath, before, after)},
        issue="602",
    )

    proc = _run(
        instructions_zip,
        "602",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RULE PACK_RECOMPUTE: PASS - recompute_match" in proc.stdout
    assert "RULE PACK_SCOPE_MAPPING: PASS - implementation_paths_ok" in proc.stdout


def _run_env(
    instructions_zip: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, str(instructions_zip)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _fake_tool(directory: Path, name: str, exit_code: int) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _git_only_env(directory: Path) -> dict[str, str]:
    env = dict(os.environ)
    git_path = subprocess.run(
        ["which", "git"], capture_output=True, text=True, check=True
    ).stdout.strip()
    link = directory / "git"
    if not link.exists():
        link.symlink_to(git_path)
    env["PATH"] = str(directory)
    return env


def test_missing_instructions_zip_continues_into_core_checks(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    missing_instructions = tmp_path / "missing.zip"
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        missing_instructions,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE VALIDATION_ERROR" not in proc.stdout
    assert "RULE INSTRUCTIONS_EXTENSION: FAIL - instructions_zip_not_found" in proc.stdout
    assert "RULE MONOLITH: PASS - gate_passed" in proc.stdout


def test_skip_external_gates_emits_cli_disabled(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})

    proc = _run(
        instructions_zip,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
        "--skip-external-gates",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RULE EXTERNAL_GATE:RUFF: SKIP - cli_disabled" in proc.stdout
    assert "RULE EXTERNAL_GATE:MYPY: SKIP - cli_disabled" in proc.stdout
    assert "RESULT: PASS" in proc.stdout


def test_external_gate_pass_when_tool_succeeds(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})
    tools = tmp_path / "tools_pass"
    tools.mkdir()
    _fake_tool(tools, "ruff", 0)
    _fake_tool(tools, "mypy", 0)
    env = _git_only_env(tools)

    proc = _run_env(
        instructions_zip,
        env,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RULE EXTERNAL_GATE:RUFF: PASS - files=1" in proc.stdout
    assert "RULE EXTERNAL_GATE:MYPY: PASS - files=1" in proc.stdout
    assert "RESULT: PASS" in proc.stdout


def test_external_gate_fail_causes_overall_fail(tmp_path: Path) -> None:
    relpath = "tests/test_sample.py"
    before = "def test_value():\n    assert 1 == 1\n"
    after = "def test_value():\n    assert 2 == 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})
    tools = tmp_path / "tools_fail"
    tools.mkdir()
    _fake_tool(tools, "pytest", 5)
    _fake_tool(tools, "ruff", 0)
    _fake_tool(tools, "mypy", 0)
    env = _git_only_env(tools)

    proc = _run_env(
        instructions_zip,
        env,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 1
    assert "RULE EXTERNAL_GATE:PYTEST: FAIL" in proc.stdout
    assert "RESULT: FAIL" in proc.stdout


def test_external_gate_unverified_does_not_force_fail(tmp_path: Path) -> None:
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    patch_zip = tmp_path / "issue_601_v2.zip"
    instructions_zip = _instructions_zip(tmp_path / "instructions.zip")
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _patch_zip(patch_zip, {_safe_member(relpath): _git_patch(relpath, before, after)})
    tools = tmp_path / "tools_unverified"
    tools.mkdir()
    env = _git_only_env(tools)

    proc = _run_env(
        instructions_zip,
        env,
        "601",
        COMMIT,
        str(patch_zip),
        "--workspace-snapshot",
        str(snapshot),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RULE EXTERNAL_GATE:RUFF: UNVERIFIED_ENVIRONMENT - tool_not_found:ruff" in proc.stdout
    assert "RULE EXTERNAL_GATE:MYPY: UNVERIFIED_ENVIRONMENT - tool_not_found:mypy" in proc.stdout
    assert "RESULT: PASS" in proc.stdout
