from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from governance.rc_resolver import build_pack, handoff_text
from scripts.patchhub.app_api_jobs import api_patch_zip_manifest
from scripts.patchhub.config import (
    AppConfig,
    AutofillConfig,
    IndexingConfig,
    IssueConfig,
    MetaConfig,
    PathsConfig,
    RunnerConfig,
    ServerConfig,
    UiConfig,
    UploadConfig,
)
from scripts.patchhub.fs_jail import FsJail
from scripts.patchhub.pm_validation_runtime import build_patch_zip_pm_validation

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "patchhub"
FOREIGN_TARGET = "audiomason2"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_bytes(relpath: str) -> bytes:
    return (REPO_ROOT / relpath).read_bytes()


def _spec_bytes() -> bytes:
    return _repo_bytes("governance/specification.jsonl")


def _governance_bytes() -> bytes:
    return _repo_bytes("governance/governance.jsonl")


def _authority_bytes(source_path: str) -> bytes:
    if source_path == "governance/governance.jsonl":
        return _governance_bytes()
    if source_path == "governance/specification.jsonl":
        return _spec_bytes()
    raise AssertionError(source_path)


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
        proc = __import__("subprocess").run(
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


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _with_spec(
    members: dict[str, bytes],
    *,
    source_path: str = "governance/specification.jsonl",
) -> dict[str, bytes]:
    out = dict(members)
    out.setdefault(source_path, _authority_bytes(source_path))
    return out


def _patch_zip(
    path: Path,
    *,
    issue: str,
    commit: str,
    members: dict[str, bytes],
    target: str | None = DEFAULT_TARGET,
) -> None:
    files = {
        "COMMIT_MESSAGE.txt": (commit + "\n").encode("ascii"),
        "ISSUE_NUMBER.txt": (issue + "\n").encode("ascii"),
        **members,
    }
    if target is not None:
        files["target.txt"] = (target + "\n").encode("ascii")
    _write_zip(path, files)


def _snapshot_zip(path: Path, members: dict[str, bytes]) -> None:
    _write_zip(path, _with_spec(members))


def _overlay_zip(path: Path, members: dict[str, bytes], *, target: str) -> None:
    payload = _with_spec(members)
    payload["target.txt"] = (target + "\n").encode("ascii")
    _write_zip(path, payload)


def _instructions_zip(
    path: Path,
    *,
    issue: str,
    source_path: str = "governance/specification.jsonl",
) -> Path:
    spec_raw = _authority_bytes(source_path)
    pack_raw = build_pack(
        spec_raw,
        "final",
        "implementation_scope",
        spec_path=source_path,
    )
    handoff = handoff_text(
        "scripts/patchhub/pm_validation_runtime.py::build_patch_zip_pm_validation",
        "implementation_scope",
        "final",
        {
            "workflow_entry_step_id": "WORKFLOW.STEP.TEST.ENTRY",
            "workflow_entry_title": "Test entry",
            "workflow_entry_surface": "SURFACE.TEST.ENTRY",
            "workflow_entry_route": "ROUTE.TEST.ENTRY",
            "allowed_next_steps": ["WORKFLOW.STEP.TEST.NEXT"],
            "required_gates": ["WORKFLOW.GATE.TEST.ENTRY"],
            "rollback_contract": ["WORKFLOW.STEP.TEST.ENTRY"],
            "workflow_human_summary": "Synthetic test workflow contract.",
        },
    )
    _write_zip(
        path,
        {
            "HANDOFF.md": handoff.encode("utf-8"),
            "constraint_pack.json": pack_raw,
            "hash_pack.txt": (hashlib.sha256(pack_raw).hexdigest() + "\n").encode("ascii"),
        },
    )
    return path


def _write_instructions_artifact(
    patches_root: Path,
    issue: str,
    *,
    source_path: str = "governance/specification.jsonl",
) -> Path:
    return _instructions_zip(
        patches_root / f"instructions_issue{issue}.zip",
        issue=issue,
        source_path=source_path,
    )


def _install_validator_runtime(tmp_path: Path) -> None:
    for relpath in (
        "governance/pm_validator.py",
        "governance/pm_validator_pack_contract.py",
        "governance/rc_resolver.py",
        "governance/specification.jsonl",
        "governance/governance.jsonl",
    ):
        dst = tmp_path / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(_repo_bytes(relpath))


def _cfg() -> AppConfig:
    return AppConfig(
        server=ServerConfig(host="127.0.0.1", port=1),
        meta=MetaConfig(version="test"),
        runner=RunnerConfig(
            command=["python3", "scripts/am_patch.py"],
            default_verbosity="normal",
            queue_enabled=False,
            runner_config_toml="scripts/am_patch/am_patch.toml",
        ),
        paths=PathsConfig(
            patches_root="patches",
            upload_dir="patches/incoming",
            allow_crud=False,
            crud_allowlist=[""],
        ),
        upload=UploadConfig(
            max_bytes=10_000_000,
            allowed_extensions=[".zip"],
            ascii_only_names=True,
        ),
        issue=IssueConfig(default_regex="issue_(\\d+)", allocation_start=1, allocation_max=999),
        indexing=IndexingConfig(log_filename_regex="x", stats_windows_days=[7]),
        ui=UiConfig(base_font_px=24, drop_overlay_enabled=False),
        autofill=AutofillConfig(
            enabled=True,
            poll_interval_seconds=10,
            scan_dir="patches",
            scan_extensions=[".zip"],
            scan_ignore_filenames=[],
            scan_ignore_prefixes=[],
            choose_strategy="mtime_ns",
            tiebreaker="lex_name",
            derive_enabled=True,
            issue_regex="^issue_(\\d+)_",
            commit_regex="^issue_\\d+_(.+)\\.zip$",
            commit_replace_underscores=True,
            commit_replace_dashes=True,
            commit_collapse_spaces=True,
            commit_trim=True,
            commit_ascii_only=True,
            issue_default_if_no_match="",
            commit_default_if_no_match="",
            overwrite_policy="if_not_dirty",
            fill_patch_path=True,
            fill_issue_id=True,
            fill_commit_message=True,
            zip_commit_enabled=True,
            zip_commit_filename="COMMIT_MESSAGE.txt",
            zip_commit_max_bytes=4096,
            zip_commit_max_ratio=200,
            zip_issue_enabled=True,
            zip_issue_filename="ISSUE_NUMBER.txt",
            zip_issue_max_bytes=128,
            zip_issue_max_ratio=200,
        ),
    )


@dataclass
class _SelfDummy:
    repo_root: Path
    cfg: AppConfig
    jail: FsJail
    patches_root: Path

    _derive_from_filename = __import__(
        "scripts.patchhub.app_api_core",
        fromlist=["_derive_from_filename"],
    )._derive_from_filename


def _mk_self(tmp_path: Path) -> _SelfDummy:
    cfg = _cfg()
    jail = FsJail(
        repo_root=tmp_path,
        patches_root_rel=cfg.paths.patches_root,
        crud_allowlist=cfg.paths.crud_allowlist,
        allow_crud=cfg.paths.allow_crud,
    )
    patches_root = jail.patches_root()
    patches_root.mkdir(parents=True, exist_ok=True)
    _install_validator_runtime(tmp_path)
    _write(
        tmp_path / "scripts" / "am_patch" / "am_patch.toml",
        "[paths]\n"
        'success_archive_name = "{repo}-{branch}_{issue}.zip"\n'
        'success_archive_dir = "patch_dir"\n'
        'success_archive_cleanup_glob_template = "audiomason2-main_*.zip"\n'
        "\n[git]\n"
        'default_branch = "main"\n',
    )
    return _SelfDummy(repo_root=tmp_path, cfg=cfg, jail=jail, patches_root=patches_root)


def test_zip_manifest_includes_pm_validation_without_initial_authority_fallback(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    current = "def value():\n    return 999\n"
    _write(tmp_path / relpath, current)
    baseline_path = s.patches_root / "patchhub-main_20260315.zip"
    instructions_path = _write_instructions_artifact(s.patches_root, "601")
    _snapshot_zip(
        baseline_path,
        {relpath: before.encode("utf-8")},
    )
    _snapshot_zip(
        s.patches_root / "audiomason2-main_20260316.zip",
        {relpath: current.encode("utf-8")},
    )
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    status, raw = api_patch_zip_manifest(s, {"path": "issue_601_v1.zip"})
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["manifest"]["patch_entry_count"] == 1
    pm_validation = payload["pm_validation"]
    assert pm_validation["status"] == "pass"
    assert pm_validation["effective_mode"] == "initial"
    assert pm_validation["authority_sources"] == [
        str(baseline_path),
        str(instructions_path),
    ]
    assert "RESULT: PASS" in pm_validation["raw_output"]


def test_build_pm_validation_requires_local_instructions_artifact(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "missing_context"
    assert payload["effective_mode"] == "initial"
    assert payload["authority_sources"] == []
    assert payload["supplemental_files"] == []
    assert "instructions_zip_missing:instructions_issue601.zip" in payload["raw_output"]


def test_build_pm_validation_initial_requires_target_matched_local_baseline(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    instructions_path = _write_instructions_artifact(s.patches_root, "601")
    _snapshot_zip(
        s.patches_root / "audiomason2-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "missing_context"
    assert payload["effective_mode"] == "initial"
    assert payload["authority_sources"] == [str(instructions_path)]
    assert "workspace_snapshot_required_for_initial_mode" in payload["raw_output"]


def test_build_pm_validation_uses_repair_overlay_only_when_available(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "scripts/sample.py"
    before = "def value():\n    return 2\n"
    after = "def value():\n    return 3\n"
    instructions_path = _write_instructions_artifact(s.patches_root, "601")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
    )
    overlay_path = s.patches_root / "patched_issue601_v01.zip"
    _overlay_zip(
        overlay_path,
        {relpath: before.encode("utf-8")},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "pass"
    assert payload["effective_mode"] == "repair-overlay-only"
    assert payload["authority_sources"] == [
        str(overlay_path),
        str(instructions_path),
    ]
    assert payload["supplemental_files"] == []


def test_build_pm_validation_repair_escalates_with_exact_supplemental_files(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "tests/test_sample.txt"
    before = "a\n"
    after = "b\n"
    baseline_path = s.patches_root / "patchhub-main_20260315.zip"
    instructions_path = _write_instructions_artifact(s.patches_root, "601")
    _write(tmp_path / relpath, before)
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
    )
    _overlay_zip(
        s.patches_root / "patched_issue601_v01.zip",
        {},
        target=DEFAULT_TARGET,
    )
    _snapshot_zip(
        baseline_path,
        {relpath: before.encode("utf-8")},
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "pass"
    assert payload["effective_mode"] == "repair-supplemental"
    assert payload["supplemental_files"] == [relpath]
    assert payload["authority_sources"] == [
        str(s.patches_root / "patched_issue601_v01.zip"),
        str(baseline_path),
        str(instructions_path),
    ]
    assert "[overlay-only]" in payload["raw_output"]
    assert "[repair-supplemental]" in payload["raw_output"]


def test_build_pm_validation_repair_uses_target_matched_baseline_outside_overlay(
    tmp_path: Path,
) -> None:
    s = _mk_self(tmp_path)
    relpath = "scripts/extra.py"
    before = "VALUE = 1\n"
    after = "VALUE = 2\n"
    baseline_path = s.patches_root / "patchhub-main_20260315.zip"
    foreign_path = s.patches_root / "audiomason2-main_20260316.zip"
    instructions_path = _write_instructions_artifact(s.patches_root, "601")
    _write(tmp_path / relpath, before)
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )
    _overlay_zip(
        s.patches_root / "patched_issue601_v01.zip",
        {},
        target=DEFAULT_TARGET,
    )
    _snapshot_zip(
        baseline_path,
        {relpath: before.encode("utf-8")},
    )
    _snapshot_zip(
        foreign_path,
        {relpath: before.encode("utf-8")},
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "pass"
    assert payload["effective_mode"] == "repair-supplemental"
    assert payload["supplemental_files"] == [relpath]
    assert payload["authority_sources"] == [
        str(s.patches_root / "patched_issue601_v01.zip"),
        str(baseline_path),
        str(instructions_path),
    ]
    assert str(foreign_path) not in payload["authority_sources"]


def test_pm_validation_uses_spec_source_for_rc_resolver(tmp_path: Path) -> None:
    s = _mk_self(tmp_path)
    relpath = "governance/rc_resolver.py"
    before = "VALUE = 1\n"
    after = "VALUE = 2\n"
    baseline_path = s.patches_root / "patchhub-main_20260317.zip"
    instructions_path = _write_instructions_artifact(
        s.patches_root,
        "602",
        source_path="governance/specification.jsonl",
    )
    _snapshot_zip(
        baseline_path,
        _with_spec(
            {relpath: before.encode("utf-8")},
            source_path="governance/specification.jsonl",
        ),
    )
    _patch_zip(
        s.patches_root / "issue_602_v1.zip",
        issue="602",
        commit="Use PM validator at zip load",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_602_v1.zip")
    assert payload["status"] == "pass"
    assert payload["effective_mode"] == "initial"
    assert payload["authority_sources"] == [
        str(baseline_path),
        str(instructions_path),
    ]
    assert "RESULT: PASS" in payload["raw_output"]
