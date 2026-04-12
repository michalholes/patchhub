from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.patchhub.app_api_editor import (  # noqa: E402
    api_editor_apply_fix,
    api_editor_document,
    api_editor_save,
    api_editor_validate,
)
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

DEFAULT_TARGET = "patchhub"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _toolkit_pm_validator_text(sig: str) -> str:
    return f"""from __future__ import annotations
import sys
print("RESULT: PASS")
print("RULE TOOLKIT_SIG: PASS - {sig}")
raise SystemExit(0)
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
    payload = {
        "remote_sig": sig,
        "archive_url": _github_archive_url(sig),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
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
class _EditorSelfDummy:
    repo_root: Path
    cfg: AppConfig


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


def _mk_self(tmp_path: Path, manifest_url: str, cache_root: Path) -> tuple[_EditorSelfDummy, Path]:
    target_root = (tmp_path / "target-repo").resolve()
    normalized_target_root = str(target_root).replace("\\", "/")
    _write(
        tmp_path / "scripts" / "am_patch" / "am_patch.toml",
        "[paths]\n"
        f'target_repo_roots = ["patchhub={normalized_target_root}"]\n'
        "\n[git]\n"
        'default_branch = "main"\n',
    )
    return _EditorSelfDummy(repo_root=tmp_path, cfg=_cfg(manifest_url, cache_root)), target_root


def _load_bytes(relpath: str) -> bytes:
    return (REPO_ROOT / relpath).read_bytes()


def _write_target_documents(target_root: Path) -> None:
    (target_root / "governance").mkdir(parents=True, exist_ok=True)
    (target_root / "governance" / "specification.jsonl").write_bytes(
        _load_bytes("governance/specification.jsonl")
    )
    (target_root / "governance" / "governance.jsonl").write_text("\n", encoding="utf-8")


@pytest.mark.usefixtures("monkeypatch")
def test_editor_document_load_resolves_toolkit_once_and_returns_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_zip = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_zip)
    self_obj, target_root = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_zip}))
    _write_target_documents(target_root)

    import scripts.patchhub.governance_toolkit_runtime as runtime_mod

    calls = {"count": 0}
    real_load = runtime_mod.load_governance_toolkit_manifest

    def counted_load(cfg):
        calls["count"] += 1
        return real_load(cfg)

    monkeypatch.setattr(runtime_mod, "load_governance_toolkit_manifest", counted_load)

    status, raw = api_editor_document(
        self_obj,
        {"target_repo": DEFAULT_TARGET, "document": "specification"},
    )
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True
    assert calls["count"] == 1
    assert payload["validated"] is True
    assert payload["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert payload["toolkit_resolution"]["resolution_mode"] == "remote-download"
    assert payload["revision_token"]
    assert not (target_root / "governance" / "validate_master_spec_v2.py").exists()


@pytest.mark.usefixtures("monkeypatch")
def test_editor_validate_and_save_reuse_pinned_toolkit_without_reresolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    toolkit_v2 = _toolkit_zip(tmp_path / "toolkit-v2.zip", "sig-v2")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1, "sig-v2": toolkit_v2})
    _install_remote_bytes(monkeypatch, remote_mapping)
    self_obj, target_root = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _write_target_documents(target_root)

    import scripts.patchhub.governance_toolkit_runtime as runtime_mod

    calls = {"count": 0}
    real_load = runtime_mod.load_governance_toolkit_manifest

    def counted_load(cfg):
        calls["count"] += 1
        return real_load(cfg)

    monkeypatch.setattr(runtime_mod, "load_governance_toolkit_manifest", counted_load)

    load_status, load_raw = api_editor_document(
        self_obj,
        {"target_repo": DEFAULT_TARGET, "document": "specification"},
    )
    assert load_status == 200
    load_payload = json.loads(load_raw.decode("utf-8"))
    assert load_payload["validated"] is True
    token = load_payload["revision_token"]
    human_text = load_payload["human_text"]
    assert calls["count"] == 1

    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v2", archive_path=toolkit_v2)
    remote_mapping[_github_manifest_url()] = manifest.read_bytes()

    validate_status, validate_raw = api_editor_validate(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": token,
            "human_text": human_text,
        },
    )
    assert validate_status == 200
    validate_payload = json.loads(validate_raw.decode("utf-8"))
    assert validate_payload["validated"] is True
    assert validate_payload["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert calls["count"] == 1

    save_status, save_raw = api_editor_save(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": validate_payload["revision_token"],
            "human_text": human_text,
        },
    )
    assert save_status == 200
    save_payload = json.loads(save_raw.decode("utf-8"))
    assert save_payload["saved"] is True
    assert save_payload["toolkit_resolution"]["selected_sig"] == "sig-v1"
    assert calls["count"] == 1


@pytest.mark.usefixtures("monkeypatch")
def test_editor_apply_fix_preserves_pinned_toolkit_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_v1 = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    toolkit_v2 = _toolkit_zip(tmp_path / "toolkit-v2.zip", "sig-v2")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_v1)
    remote_mapping = _remote_mapping(manifest, {"sig-v1": toolkit_v1, "sig-v2": toolkit_v2})
    _install_remote_bytes(monkeypatch, remote_mapping)
    self_obj, target_root = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _write_target_documents(target_root)

    load_status, load_raw = api_editor_document(
        self_obj,
        {"target_repo": DEFAULT_TARGET, "document": "specification"},
    )
    assert load_status == 200
    load_payload = json.loads(load_raw.decode("utf-8"))
    assert load_payload["validated"] is True

    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v2", archive_path=toolkit_v2)
    remote_mapping[_github_manifest_url()] = manifest.read_bytes()

    apply_status, apply_raw = api_editor_apply_fix(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": load_payload["revision_token"],
            "human_text": load_payload["human_text"],
            "action_id": "recompute_meta_counts",
            "primary_id": "",
            "secondary_id": "",
        },
    )
    assert apply_status == 200
    apply_payload = json.loads(apply_raw.decode("utf-8"))
    assert apply_payload["ok"] is True
    assert apply_payload["toolkit_resolution"]["selected_sig"] == "sig-v1"

    validate_status, validate_raw = api_editor_validate(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": apply_payload["revision_token"],
            "human_text": apply_payload["human_text"],
        },
    )
    assert validate_status == 200
    validate_payload = json.loads(validate_raw.decode("utf-8"))
    assert validate_payload["validated"] is True
    assert validate_payload["toolkit_resolution"]["selected_sig"] == "sig-v1"


@pytest.mark.usefixtures("monkeypatch")
def test_editor_validate_and_save_fail_explicitly_without_session_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit_zip = _toolkit_zip(tmp_path / "toolkit-v1.zip", "sig-v1")
    manifest = _write_manifest(tmp_path / "manifest.json", sig="sig-v1", archive_path=toolkit_zip)
    self_obj, target_root = _mk_self(tmp_path, _github_manifest_url(), tmp_path / "toolkit-cache")
    _install_remote_bytes(monkeypatch, _remote_mapping(manifest, {"sig-v1": toolkit_zip}))
    _write_target_documents(target_root)

    validate_status, validate_raw = api_editor_validate(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": "missing-token",
            "human_text": "# PHB-HR-TOML v1\n",
        },
    )
    assert validate_status == 200
    validate_payload = json.loads(validate_raw.decode("utf-8"))
    assert validate_payload["validated"] is False
    assert validate_payload["failure"]["failure_code"] == "missing_revision_state"
    assert validate_payload["toolkit_resolution"] == {}

    save_status, save_raw = api_editor_save(
        self_obj,
        {
            "target_repo": DEFAULT_TARGET,
            "document": "specification",
            "revision_token": "missing-token",
            "human_text": "# PHB-HR-TOML v1\n",
        },
    )
    assert save_status == 200
    save_payload = json.loads(save_raw.decode("utf-8"))
    assert save_payload["saved"] is False
    assert save_payload["failure"]["failure_code"] == "missing_revision_state"
    assert save_payload["toolkit_resolution"] == {}
