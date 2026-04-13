from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.patchhub.app_api_jobs import api_patch_zip_manifest  # noqa: E402
from scripts.patchhub.config import (  # noqa: E402
    AppConfig,
    AutofillConfig,
    GovernanceToolkitConfig,
    IndexingConfig,
    IssueConfig,
    MetaConfig,
    PathsConfig,
    RunnerConfig,
    ServerConfig,
    TargetingConfig,
    UiConfig,
    UploadConfig,
)
from scripts.patchhub.fs_jail import FsJail  # noqa: E402
from scripts.patchhub.pm_validation_runtime import build_patch_zip_pm_validation  # noqa: E402

DEFAULT_TARGET = "patchhub"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_member(relpath: str) -> str:
    return "patches/per_file/" + relpath.replace("/", "__") + ".patch"


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


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


def _patch_zip(
    path: Path,
    *,
    issue: str,
    commit: str,
    members: dict[str, bytes],
    target: str | None = DEFAULT_TARGET,
) -> None:
    payload = {
        "COMMIT_MESSAGE.txt": (commit + "\n").encode("ascii"),
        "ISSUE_NUMBER.txt": (issue + "\n").encode("ascii"),
        **members,
    }
    if target is not None:
        payload["target.txt"] = (target + "\n").encode("ascii")
    _write_zip(path, payload)


def _snapshot_zip(path: Path, members: dict[str, bytes]) -> None:
    _write_zip(path, members)


def _overlay_zip(path: Path, members: dict[str, bytes], *, target: str) -> None:
    payload = dict(members)
    payload["target.txt"] = (target + "\n").encode("ascii")
    _write_zip(path, payload)


def _instructions_zip(path: Path) -> None:
    _write_zip(
        path,
        {
            "HANDOFF.md": b"handoff\n",
            "constraint_pack.json": b"{}\n",
            "hash_pack.txt": (hashlib.sha256(b"{}\n").hexdigest() + "\n").encode("ascii"),
        },
    )


def _toolkit_pm_validator_text(sig: str) -> str:
    return f"""from __future__ import annotations
import sys
from pathlib import Path
from zipfile import ZipFile

PATCH_PREFIX = "patches/per_file/"
PATCH_SUFFIX = ".patch"


def _paths(path: Path) -> list[str]:
    out = []
    with ZipFile(path, "r") as zf:
        for name in zf.namelist():
            if not name.startswith(PATCH_PREFIX) or not name.endswith(PATCH_SUFFIX):
                continue
            rel = name[len(PATCH_PREFIX):-len(PATCH_SUFFIX)].replace("__", "/")
            out.append(rel)
    return sorted(out)


def main(argv: list[str]) -> int:
    issue_id, commit_message, patch_path, instructions_path = argv[:4]
    workspace_snapshot = None
    repair_overlay = None
    supplemental = []
    idx = 4
    while idx < len(argv):
        flag = argv[idx]
        if flag == "--workspace-snapshot":
            workspace_snapshot = Path(argv[idx + 1])
            idx += 2
            continue
        if flag == "--repair-overlay":
            repair_overlay = Path(argv[idx + 1])
            idx += 2
            continue
        if flag == "--supplemental-file":
            supplemental.append(argv[idx + 1])
            idx += 2
            continue
        idx += 1
    print("SIG:{sig}")
    if not Path(instructions_path).is_file():
        print("RESULT: FAIL")
        print("RULE INSTRUCTIONS_EXTENSION: FAIL - instructions_zip_not_found")
        return 1
    if repair_overlay is not None and not supplemental:
        patch_paths = _paths(Path(patch_path))
        overlay_paths = set(_paths(repair_overlay))
        missing = [path for path in patch_paths if path not in overlay_paths]
        if missing:
            print("RESULT: FAIL")
            print(f"repair_requires_supplemental_file:{{missing!r}}")
            return 1
    print("RESULT: PASS")
    print("RULE EXTERNAL_GATE:RUFF: SKIP - cli_disabled")
    print(f"RULE TOOLKIT_SIG: PASS - {sig}")
    print(f"RULE WORKSPACE: PASS - {{workspace_snapshot}}")
    print(f"RULE ISSUE: PASS - {{issue_id}}")
    print(f"RULE COMMIT: PASS - {{commit_message}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""


def _toolkit_validate_text(sig: str) -> str:
    return f"""from __future__ import annotations
import json
import sys
from pathlib import Path


def main(path: str) -> int:
    for idx, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"validator {sig} line {{idx}} invalid: {{exc.msg}}")
            return 1
    print("validator {sig} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
"""


def _toolkit_zip(path: Path, sig: str, *, prefix: str = "") -> Path:
    root = f"{prefix.rstrip('/')}/" if prefix else ""
    _write_zip(
        path,
        {
            root + "governance/pm_validator.py": _toolkit_pm_validator_text(sig).encode("utf-8"),
            root + "governance/validate_master_spec_v2.py": _toolkit_validate_text(sig).encode(
                "utf-8"
            ),
        },
    )
    return path


def _write_manifest(path: Path, *, sig: str, archive_path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "remote_sig": sig,
        "archive_url": _github_archive_url(sig),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _github_manifest_url() -> str:
    return (
        "https://raw.githubusercontent.com/example/standalone-governance-toolkit/main/manifest.json"
    )


def _github_archive_url(sig: str) -> str:
    return (
        "https://github.com/example/standalone-governance-toolkit/"
        f"releases/download/{sig}/toolkit.zip"
    )


def _remote_mapping(manifest_path: Path, archive_paths: dict[str, Path]) -> dict[str, bytes]:
    return {
        _github_manifest_url(): manifest_path.read_bytes(),
        **{_github_archive_url(sig): path.read_bytes() for sig, path in archive_paths.items()},
    }


def _install_remote_bytes(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, bytes]) -> None:
    import scripts.patchhub.governance_toolkit_runtime as runtime_mod

    def fake_read_remote_bytes(url: str, *, timeout_s: int) -> bytes:
        del timeout_s
        if url not in mapping:
            raise ValueError(f"remote_not_found:{url}")
        return mapping[url]

    monkeypatch.setattr(runtime_mod, "_read_remote_bytes", fake_read_remote_bytes)


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


def _cfg(manifest_url: str, cache_root: Path) -> AppConfig:
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
        targeting=TargetingConfig(default_target_repo=DEFAULT_TARGET),
        governance_toolkit=GovernanceToolkitConfig(
            github_manifest_url=str(manifest_url),
            cache_root=str(cache_root),
            allow_stale=False,
            request_timeout_s=3,
        ),
    )


def _mk_self(tmp_path: Path, manifest_url: str, cache_root: Path) -> _SelfDummy:
    cfg = _cfg(manifest_url, cache_root)
    jail = FsJail(
        repo_root=tmp_path,
        patches_root_rel=cfg.paths.patches_root,
        crud_allowlist=cfg.paths.crud_allowlist,
        allow_crud=cfg.paths.allow_crud,
    )
    patches_root = jail.patches_root()
    patches_root.mkdir(parents=True, exist_ok=True)
    target_root = str((tmp_path / "target-repo").resolve()).replace("\\", "/")
    _write(
        tmp_path / "scripts" / "am_patch" / "am_patch.toml",
        "[paths]\n"
        'success_archive_name = "{repo}-{branch}_{issue}.zip"\n'
        'success_archive_dir = "patch_dir"\n'
        'success_archive_cleanup_glob_template = "patchhub-main_*.zip"\n'
        f'target_repo_roots = ["patchhub={target_root}"]\n'
        "\n[git]\n"
        'default_branch = "main"\n',
    )
    return _SelfDummy(repo_root=tmp_path, cfg=cfg, jail=jail, patches_root=patches_root)


@pytest.mark.usefixtures("monkeypatch")
def test_patch_zip_manifest_uses_standalone_toolkit_and_surfaces_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_v1}))

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    snapshot = s.patches_root / "patchhub-main_20260315.zip"
    instructions = s.patches_root / "instructions_601_v1.zip"
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _instructions_zip(instructions)
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Use standalone toolkit",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    import scripts.patchhub.governance_toolkit_runtime as runtime_mod

    calls = {"count": 0}
    real_load = runtime_mod.load_governance_toolkit_manifest

    def counted_load(cfg):
        calls["count"] += 1
        return real_load(cfg)

    monkeypatch.setattr(runtime_mod, "load_governance_toolkit_manifest", counted_load)

    status, raw = api_patch_zip_manifest(s, {"path": "issue_601_v1.zip"})
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    pm = payload["pm_validation"]
    assert calls["count"] == 1
    assert pm["status"] == "pass"
    assert pm["effective_mode"] == "initial"
    assert pm["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert pm["toolkit_resolution"]["resolution_mode"] == "remote-download"
    assert pm["toolkit_resolution"]["download_performed"] is True
    assert pm["toolkit_resolution"]["integrity_check_result"] == "pass"
    assert pm["authority_sources"] == [
        str(snapshot),
        str(instructions),
    ]
    assert pm["failure_summary"] == ""
    assert "RESULT: PASS" in pm["raw_output"]
    assert "SIG:sig-v1" in pm["raw_output"]
    assert not (tmp_path / "governance" / "pm_validator.py").exists()


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_reports_instructions_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_v1}))
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")

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
        commit="Missing instructions",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "fail"
    assert payload["failure_summary"] == "missing or invalid instructions artifact"
    assert "RULE INSTRUCTIONS_EXTENSION: FAIL" in payload["raw_output"]


def test_failure_summary_classifier_covers_phb_generated_prevalidator_failure() -> None:
    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    assert (
        pm_runtime_mod._failure_summary("zip_target_missing_or_invalid:missing", {})
        == "missing or invalid zip metadata"
    )
    assert pm_runtime_mod._failure_summary("", {}) == "generic validator failure"


def test_failure_summary_classifier_does_not_promote_stale_cache_warning() -> None:
    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    assert (
        pm_runtime_mod._failure_summary(
            "RESULT: FAIL\nRULE MONOLITH: FAIL - file_too_large\n",
            {"resolution_mode": "stale-cache", "error": "remote_not_found"},
        )
        == "monolith"
    )


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_reports_validator_rule_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_v1}))
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _instructions_zip(s.patches_root / "instructions_601_v1.zip")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Monolith failure summary",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    def fake_run_validator(**kwargs):
        del kwargs
        return __import__("subprocess").CompletedProcess(
            args=["pm_validator.py"],
            returncode=1,
            stdout="RESULT: FAIL\nRULE MONOLITH: FAIL - file_too_large\n",
            stderr="",
        )

    monkeypatch.setattr(pm_runtime_mod, "_run_validator", fake_run_validator)

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "fail"
    assert payload["failure_summary"] == "monolith"
    assert "RULE MONOLITH: FAIL" in payload["raw_output"]


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_repair_supplemental_reuses_pinned_toolkit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    toolkit_v2 = _toolkit_zip(tmp_path / "toolkit-v2.zip", "sig-v2")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1, "sig-v2": toolkit_v2})
    _install_remote_bytes(monkeypatch, remote_mapping)
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")

    relpath = "tests/test_sample.txt"
    before = "a\n"
    after = "b\n"
    snapshot = s.patches_root / "patchhub-main_20260315.zip"
    instructions = s.patches_root / "instructions_601_v1.zip"
    overlay = s.patches_root / "patched_issue601_v01.zip"
    _snapshot_zip(snapshot, {relpath: before.encode("utf-8")})
    _instructions_zip(instructions)
    _overlay_zip(overlay, {}, target=DEFAULT_TARGET)
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Reuse pinned toolkit",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    import scripts.patchhub.governance_toolkit_runtime as runtime_mod
    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    load_calls = {"count": 0}
    validator_paths: list[str] = []
    real_load = runtime_mod.load_governance_toolkit_manifest
    real_run = pm_runtime_mod._run_validator

    def counted_load(cfg):
        load_calls["count"] += 1
        return real_load(cfg)

    def wrapped_run(**kwargs):
        validator_paths.append(str(kwargs["validator_script"]))
        if len(validator_paths) == 1:
            _write_manifest(manifest, sig="sig-v2", archive_path=toolkit_v2)
            remote_mapping[_github_manifest_url()] = manifest.read_bytes()
        return real_run(**kwargs)

    monkeypatch.setattr(runtime_mod, "load_governance_toolkit_manifest", counted_load)
    monkeypatch.setattr(pm_runtime_mod, "_run_validator", wrapped_run)

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "pass"
    assert payload["effective_mode"] == "repair-supplemental"
    assert payload["supplemental_files"] == [relpath]
    assert payload["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert load_calls["count"] == 1
    assert len(validator_paths) == 2
    assert validator_paths[0] == validator_paths[1]
    assert "versions/sig-v1/" in validator_paths[0]
    assert payload["authority_sources"] == [
        str(overlay),
        str(snapshot),
        str(instructions),
    ]
    assert payload["failure_summary"] == ""
    assert "SIG:sig-v1" in payload["raw_output"]


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_fails_closed_without_authority_or_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _install_remote_bytes(monkeypatch, {})

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _instructions_zip(s.patches_root / "instructions_601_v1.zip")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Fail closed",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "fail"
    assert payload["failure_summary"] == "toolkit resolution"
    assert payload["toolkit_resolution"]["resolution_mode"] == "fail-closed"
    assert payload["toolkit_resolution"]["error"]
    assert payload["authority_sources"] == []


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_reports_stale_cache_when_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1})
    _install_remote_bytes(monkeypatch, remote_mapping)
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    s.cfg = AppConfig(
        **{
            **s.cfg.__dict__,
            "governance_toolkit": GovernanceToolkitConfig(
                github_manifest_url=_github_manifest_url(),
                cache_root=str(tmp_path / "toolkit-cache"),
                allow_stale=True,
                request_timeout_s=3,
            ),
        }
    )

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _instructions_zip(s.patches_root / "instructions_601_v1.zip")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Allow stale cache",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    first = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert first["status"] == "pass"
    assert first["failure_summary"] == ""
    assert first["toolkit_resolution"]["selected_sig"] == "sig-v1"

    remote_mapping.pop(_github_manifest_url(), None)
    second = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert second["status"] == "pass"
    assert second["failure_summary"] == ""
    assert second["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert second["toolkit_resolution"]["resolution_mode"] == "stale-cache"
    assert second["toolkit_resolution"]["error"]


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_stale_cache_preserves_final_validator_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1})
    _install_remote_bytes(monkeypatch, remote_mapping)
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    s.cfg = AppConfig(
        **{
            **s.cfg.__dict__,
            "governance_toolkit": GovernanceToolkitConfig(
                github_manifest_url=_github_manifest_url(),
                cache_root=str(tmp_path / "toolkit-cache"),
                allow_stale=True,
                request_timeout_s=3,
            ),
        }
    )

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _instructions_zip(s.patches_root / "instructions_601_v1.zip")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Stale cache keeps monolith summary",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    remote_mapping.pop(_github_manifest_url(), None)

    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    def fake_run_validator(**kwargs):
        del kwargs
        return __import__("subprocess").CompletedProcess(
            args=["pm_validator.py"],
            returncode=1,
            stdout="RESULT: FAIL\nRULE MONOLITH: FAIL - file_too_large\n",
            stderr="",
        )

    monkeypatch.setattr(pm_runtime_mod, "_run_validator", fake_run_validator)

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "fail"
    assert payload["toolkit_resolution"]["resolution_mode"] == "stale-cache"
    assert payload["toolkit_resolution"]["error"]
    assert payload["failure_summary"] == "monolith"


@pytest.mark.usefixtures("monkeypatch")
def test_patch_validation_empty_raw_output_uses_generic_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_v1}))
    s = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")

    relpath = "scripts/sample.py"
    before = "def value():\n    return 1\n"
    after = "def value():\n    return 2\n"
    _snapshot_zip(
        s.patches_root / "patchhub-main_20260315.zip",
        {relpath: before.encode("utf-8")},
    )
    _instructions_zip(s.patches_root / "instructions_601_v1.zip")
    _patch_zip(
        s.patches_root / "issue_601_v1.zip",
        issue="601",
        commit="Generic summary on empty output",
        members={_safe_member(relpath): _git_patch(relpath, before, after)},
        target=DEFAULT_TARGET,
    )

    import scripts.patchhub.pm_validation_runtime as pm_runtime_mod

    def fake_run_validator(**kwargs):
        del kwargs
        return __import__("subprocess").CompletedProcess(
            args=["pm_validator.py"],
            returncode=1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(pm_runtime_mod, "_run_validator", fake_run_validator)

    payload = build_patch_zip_pm_validation(s, "issue_601_v1.zip")
    assert payload["status"] == "fail"
    assert payload["raw_output"] == ""
    assert payload["failure_summary"] == "generic validator failure"


@pytest.mark.usefixtures("monkeypatch")
def test_resolver_stale_cache_is_scoped_to_current_authority_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.patchhub.governance_toolkit_runtime import (
        GovernanceToolkitRuntimeError,
        resolve_governance_toolkit,
    )

    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1})
    _install_remote_bytes(monkeypatch, remote_mapping)

    cache_root = tmp_path / "toolkit-cache"
    selection = resolve_governance_toolkit(_cfg(_github_manifest_url(), cache_root))
    assert selection.selected_sig == "sig-v1"

    other_manifest_url = (
        "https://raw.githubusercontent.com/example/other-standalone-governance-toolkit/"
        "main/manifest.json"
    )
    cfg_other = AppConfig(
        **{
            **_cfg(other_manifest_url, cache_root).__dict__,
            "governance_toolkit": GovernanceToolkitConfig(
                github_manifest_url=other_manifest_url,
                cache_root=str(cache_root),
                allow_stale=True,
                request_timeout_s=3,
            ),
        }
    )

    with pytest.raises(GovernanceToolkitRuntimeError) as excinfo:
        resolve_governance_toolkit(cfg_other)

    resolution = excinfo.value.resolution
    assert resolution["resolution_mode"] == "fail-closed"
    assert resolution["selected_sig"] == ""
    assert resolution["cached_sig_before"] == ""


@pytest.mark.usefixtures("monkeypatch")
def test_resolver_accepts_archive_with_single_top_level_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.patchhub.governance_toolkit_runtime import resolve_governance_toolkit

    toolkit_v1 = _toolkit_zip(
        tmp_path / "toolkit-v1.zip",
        "sig-v1",
        prefix="standalone-governance-toolkit-deadbeef",
    )
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_v1}))

    selection = resolve_governance_toolkit(_cfg(_github_manifest_url(), tmp_path / "toolkit-cache"))
    assert selection.selected_sig == "sig-v1"
    assert selection.resolution["resolution_mode"] == "remote-download"
    assert selection.pm_validator_path.is_file()
    assert selection.validate_master_spec_v2_path.is_file()
    assert str(selection.pm_validator_path).endswith("versions/sig-v1/governance/pm_validator.py")
