from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

COMMIT_MESSAGE = "Add PM patch validator tool"
SCRIPT_REL = Path("scripts/pm_validator.py")
PATCH_REL = Path("patches/issue_223_v1.zip")
DEFAULT_TARGET = "patchhub"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / SCRIPT_REL


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
        patch = proc.stdout
        patch = patch.replace(f"a/old/{relpath}", f"a/{relpath}")
        patch = patch.replace(f"b/new/{relpath}", f"b/{relpath}")
        return patch.encode("utf-8")


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


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


def _pack_bytes(spec_raw: bytes) -> bytes:
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
        "target_scope": "implementation_scope",
        "mode": "final",
        "spec_fingerprint": hashlib.sha256(spec_raw).hexdigest(),
        "binding_meta_id": "binding-meta-1",
        "active_bindings": [active_binding],
        "active_rule_ids": ["pack-rule-1"],
        "full_rule_text": {"pack-rule-1": "constraint pack enforcement"},
        "match_basis": {"pack-rule-1": {"phase": "final", "target": "implementation_scope"}},
        "authoritative_sources": ["docs/specification.jsonl"],
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
            "mode": "final",
            "target_scope": "implementation_scope",
        },
    }
    return (json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _write_instructions_zip(path: Path) -> Path:
    spec_raw = _spec_bytes()
    pack_raw = _pack_bytes(spec_raw)
    _write_zip(
        path,
        {
            "HANDOFF.md": b"SPEC CONTEXT\nPM version used: resolver-generated\n",
            "constraint_pack.json": pack_raw,
            "hash_pack.txt": (hashlib.sha256(pack_raw).hexdigest() + "\n").encode("ascii"),
        },
    )
    return path


def _write_workspace_snapshot(repo_root: Path, snapshot_path: Path) -> Path:
    members: dict[str, bytes] = {"docs/specification.jsonl": _spec_bytes()}
    for file_path in repo_root.rglob("*"):
        if file_path.is_file():
            relpath = str(file_path.relative_to(repo_root)).replace("\\", "/")
            members[relpath] = file_path.read_bytes()
    _write_zip(snapshot_path, members)
    return snapshot_path


def _write_patch_zip(
    repo_root: Path,
    *,
    issue_id: str,
    commit_message: str,
    members: dict[str, bytes],
    include_commit: bool = True,
    include_issue: bool = True,
    extra_files: dict[str, bytes] | None = None,
    patch_rel: Path = PATCH_REL,
    target: str | None = DEFAULT_TARGET,
) -> Path:
    patch_path = repo_root / patch_rel
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(patch_path, "w", compression=ZIP_DEFLATED) as zf:
        if include_commit:
            zf.writestr("COMMIT_MESSAGE.txt", commit_message + "\n")
        if include_issue:
            zf.writestr("ISSUE_NUMBER.txt", issue_id + "\n")
        if target is not None and "target.txt" not in (extra_files or {}):
            zf.writestr("target.txt", target + "\n")
        for name, data in members.items():
            zf.writestr(name, data)
        for name, data in (extra_files or {}).items():
            zf.writestr(name, data)
    return patch_path


def _run_validator(
    repo_root: Path,
    issue_id: str,
    commit_message: str,
    *,
    snapshot_path: Path,
    instructions_path: Path,
    patch_rel: Path = PATCH_REL,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            issue_id,
            commit_message,
            str(repo_root / patch_rel),
            str(instructions_path),
            "--workspace-snapshot",
            str(snapshot_path),
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )


def _fragment_member(
    relpath: str = "docs/change_fragments/validator.md", text: str = "added\n"
) -> tuple[str, bytes]:
    member = "patches/per_file/" + relpath.replace("/", "__") + ".patch"
    added_lines = text.splitlines()
    hunk = "".join(f"+{line}\n" for line in added_lines)
    patch = (
        f"diff --git a/{relpath} b/{relpath}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{relpath}\n"
        f"@@ -0,0 +1,{len(added_lines)} @@\n"
        f"{hunk}"
    ).encode()
    return member, patch


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


def test_valid_patch_passes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: PASS" in proc.stdout
    assert f"RULE TARGET_FILE: PASS - {DEFAULT_TARGET}" in proc.stdout
    assert "RULE PER_FILE_LAYOUT: PASS" in proc.stdout
    assert "RULE GIT_APPLY_CHECK:patches/per_file/docs__readme.txt.patch: PASS" in proc.stdout


def test_missing_target_file_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
        target=None,
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE TARGET_FILE: FAIL - missing_target_file" in proc.stdout


def test_valid_patch_passes_with_target_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
        extra_files={"target.txt": f"{DEFAULT_TARGET}\n".encode("ascii")},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"RULE TARGET_FILE: PASS - {DEFAULT_TARGET}" in proc.stdout


def test_patch_basename_failure_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
        patch_rel=Path("patches/test_patch.zip"),
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
        patch_rel=Path("patches/test_patch.zip"),
    )
    assert proc.returncode == 1
    assert "RULE PATCH_BASENAME: FAIL" in proc.stdout


def test_patch_basename_issue_mismatch_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
        patch_rel=Path("patches/issue_999_v1.zip"),
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
        patch_rel=Path("patches/issue_999_v1.zip"),
    )
    assert proc.returncode == 1
    assert "RULE PATCH_BASENAME: FAIL" in proc.stdout
    assert "issue_mismatch:expected=223:actual=999:name=issue_999_v1.zip" in proc.stdout


def test_patch_basename_version_zero_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
        patch_rel=Path("patches/issue_223_v0.zip"),
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
        patch_rel=Path("patches/issue_223_v0.zip"),
    )
    assert proc.returncode == 1
    assert "RULE PATCH_BASENAME: FAIL" in proc.stdout
    assert "invalid_patch_basename:issue_223_v0.zip" in proc.stdout


def test_missing_commit_message_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
        include_commit=False,
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE COMMIT_MESSAGE_FILE: FAIL" in proc.stdout


def test_issue_number_mismatch_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="999",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE ISSUE_NUMBER_FILE: FAIL" in proc.stdout


def test_extra_zip_entry_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
        extra_files={"notes.txt": b"x\n"},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert f"RULE TARGET_FILE: PASS - {DEFAULT_TARGET}" in proc.stdout
    assert "RULE PER_FILE_LAYOUT: FAIL - extra_entries=['notes.txt']" in proc.stdout


def test_git_apply_failure_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "current\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE GIT_APPLY_CHECK:patches/per_file/docs__readme.txt.patch: FAIL" in proc.stdout


def test_line_length_rule_skips_non_python_and_non_js_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    long_line = "x" * 101
    patch = _git_patch("docs/readme.txt", "old\n", long_line + "\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RULE LINE_LENGTH: PASS" in proc.stdout


def test_line_length_failure_is_reported_for_python(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "scripts/example.py", "x = 1\n")
    long_line = "x" * 101
    patch = _git_patch("scripts/example.py", "x = 1\n", long_line + "\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/scripts__example.py.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE LINE_LENGTH: FAIL" in proc.stdout


def test_line_length_failure_is_reported_for_js(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "scripts/example.js", "const value = 1;\n")
    long_line = "x" * 101
    patch = _git_patch(
        "scripts/example.js",
        "const value = 1;\n",
        f"const value = '{long_line}';\n",
    )
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/scripts__example.js.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE LINE_LENGTH: FAIL" in proc.stdout


def test_monolith_threshold_crossing_failure_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    relpath = "scripts/threshold_large.py"
    before = _module_text(exports=10, values=633)
    after = _module_text(exports=13, values=987)
    _write(repo_root / relpath, before)
    patch = _git_patch(relpath, before, after)
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/scripts__threshold_large.py.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE MONOLITH: FAIL" in proc.stdout


def test_monolith_failure_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "scripts/existing.py", "x = 1\n")
    patch = (
        b"diff --git a/scripts/common.py b/scripts/common.py\n"
        b"new file mode 100644\n"
        b"index 0000000..1111111\n"
        b"--- /dev/null\n"
        b"+++ b/scripts/common.py\n"
        b"@@ -0,0 +1,2 @@\n"
        b"+def ok() -> int:\n"
        b"+    return 1\n"
    )
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/scripts__common.py.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE MONOLITH: FAIL" in proc.stdout
    assert "catchall_forbidden:scripts/common.py" in proc.stdout


NODE_AVAILABLE = shutil.which("node") is not None


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node is required")
def test_js_syntax_failure_is_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "scripts/test.js", "const x = 1;\n")
    patch = _git_patch("scripts/test.js", "const x = 1;\n", "const x = ;\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/scripts__test.js.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE JS_SYNTAX: FAIL" in proc.stdout


def test_docs_gate_failure_is_reported_without_fragment(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={"patches/per_file/docs__readme.txt.patch": patch},
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE DOCS_GATE: FAIL - missing_change_fragment" in proc.stdout


def test_docs_gate_failure_is_reported_for_direct_changes_md_edit(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/changes.md", "old\n")
    patch = _git_patch("docs/changes.md", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__changes.md.patch": patch,
            fragment_member: fragment_patch,
        },
    )
    _write_workspace_snapshot(repo_root, snapshot_path)

    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 1
    assert "RULE DOCS_GATE: FAIL - direct_changes_md_edit" in proc.stdout


def test_no_manual_only_output(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    snapshot_path = tmp_path / f"{DEFAULT_TARGET}-main_666.zip"
    instructions_path = _write_instructions_zip(tmp_path / "instructions.zip")
    _write(repo_root / "docs/readme.txt", "old\n")
    patch = _git_patch("docs/readme.txt", "old\n", "new\n")
    fragment_member, fragment_patch = _fragment_member()
    _write_patch_zip(
        repo_root,
        issue_id="223",
        commit_message=COMMIT_MESSAGE,
        members={
            "patches/per_file/docs__readme.txt.patch": patch,
            fragment_member: fragment_patch,
        },
    )
    _write_workspace_snapshot(repo_root, snapshot_path)
    proc = _run_validator(
        repo_root,
        "223",
        COMMIT_MESSAGE,
        snapshot_path=snapshot_path,
        instructions_path=instructions_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "MANUAL_ONLY" not in proc.stdout
