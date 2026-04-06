from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.artifacts import build_artifacts
    from am_patch.config import Policy
    from am_patch.errors import RunnerError
    from am_patch.failure_zip import cleanup_on_success_commit

    return Policy, RunnerError, build_artifacts, cleanup_on_success_commit


class _FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    def section(self, _name: str) -> None:
        return


def _paths(tmp_path: Path) -> SimpleNamespace:
    paths = SimpleNamespace(
        patch_dir=tmp_path / "patches",
        successful_dir=tmp_path / "patches" / "successful",
        artifacts_dir=tmp_path / "patches" / "artifacts",
        logs_dir=tmp_path / "patches" / "logs",
    )
    for path in (paths.patch_dir, paths.successful_dir, paths.artifacts_dir, paths.logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def test_failure_zip_disabled_skips_create_and_cleanup(tmp_path: Path) -> None:
    policy_cls, _runner_error, build_artifacts, _cleanup = _import_am_patch()
    logger = _FakeLogger()
    paths = _paths(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    log_path = paths.logs_dir / "run.log"
    log_path.write_text("log\n", encoding="utf-8")
    stale = paths.patch_dir / "patched_issue123_old.zip"
    stale.write_text("old", encoding="utf-8")

    policy = policy_cls()
    policy.failure_zip_enabled = False

    summary = build_artifacts(
        logger=logger,
        cli=SimpleNamespace(issue_id=123),
        policy=policy,
        paths=paths,
        repo_root=repo_root,
        log_path=log_path,
        exit_code=1,
        unified_mode=False,
        patch_applied_successfully=False,
        archived_patch=None,
        failed_patch_blobs_for_zip=[],
        files_for_fail_zip=["alpha.py"],
        ws_repo_for_fail_zip=repo_root,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        ws_attempt=1,
        effective_target_repo_name="patchhub",
    )

    assert summary.failure_zip is None
    assert stale.exists()


def test_cleanup_on_success_commit_is_noop_when_failure_zip_disabled(tmp_path: Path) -> None:
    policy_cls, _runner_error, _build_artifacts, cleanup_on_success_commit = _import_am_patch()
    patch_dir = tmp_path / "patches"
    patch_dir.mkdir()
    doomed = patch_dir / "patched_issue123_v01.zip"
    doomed.write_text("zip", encoding="utf-8")

    policy = policy_cls()
    policy.failure_zip_enabled = False
    policy.failure_zip_delete_on_success_commit = True

    cleanup_on_success_commit(patch_dir=patch_dir, policy=policy, issue="123")

    assert doomed.exists()


def test_success_archive_disabled_skips_archive_and_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, _runner_error, build_artifacts, _cleanup = _import_am_patch()
    logger = _FakeLogger()
    paths = _paths(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    log_path = paths.logs_dir / "run.log"
    log_path.write_text("log\n", encoding="utf-8")
    stale = paths.patch_dir / "repo-main-old.zip"
    stale.write_text("old", encoding="utf-8")

    from am_patch import artifacts as artifacts_mod

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("success archive helpers should not run")

    monkeypatch.setattr(artifacts_mod.git_ops, "current_branch", _unexpected)
    monkeypatch.setattr(artifacts_mod.git_ops, "head_commit_epoch_s", _unexpected)
    monkeypatch.setattr(artifacts_mod.git_ops, "git_archive", _unexpected)

    policy = policy_cls()
    policy.success_archive_enabled = False
    policy.issue_diff_bundle_enabled = False
    policy.success_archive_cleanup_glob_template = "repo-main-*.zip"
    policy.success_archive_keep_count = 0

    summary = build_artifacts(
        logger=logger,
        cli=SimpleNamespace(issue_id=123),
        policy=policy,
        paths=paths,
        repo_root=repo_root,
        log_path=log_path,
        exit_code=0,
        unified_mode=False,
        patch_applied_successfully=True,
        archived_patch=None,
        failed_patch_blobs_for_zip=[],
        files_for_fail_zip=[],
        ws_repo_for_fail_zip=repo_root,
        issue_diff_base_sha=None,
        issue_diff_paths=["alpha.py"],
        ws_attempt=None,
        effective_target_repo_name="patchhub",
    )

    assert summary.success_zip is None
    assert stale.exists()


def test_issue_diff_disabled_allows_missing_base_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, _runner_error, build_artifacts, _cleanup = _import_am_patch()
    logger = _FakeLogger()
    paths = _paths(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    log_path = paths.logs_dir / "run.log"
    log_path.write_text("log\n", encoding="utf-8")

    from am_patch import artifacts as artifacts_mod

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("success archive helpers should not run")

    monkeypatch.setattr(artifacts_mod.git_ops, "current_branch", _unexpected)
    monkeypatch.setattr(artifacts_mod.git_ops, "head_commit_epoch_s", _unexpected)
    monkeypatch.setattr(artifacts_mod.git_ops, "git_archive", _unexpected)

    policy = policy_cls()
    policy.success_archive_enabled = False
    policy.issue_diff_bundle_enabled = False

    summary = build_artifacts(
        logger=logger,
        cli=SimpleNamespace(issue_id=123),
        policy=policy,
        paths=paths,
        repo_root=repo_root,
        log_path=log_path,
        exit_code=0,
        unified_mode=False,
        patch_applied_successfully=True,
        archived_patch=None,
        failed_patch_blobs_for_zip=[],
        files_for_fail_zip=[],
        ws_repo_for_fail_zip=repo_root,
        issue_diff_base_sha=None,
        issue_diff_paths=["alpha.py"],
        ws_attempt=None,
        effective_target_repo_name="patchhub",
    )

    assert summary.issue_diff_zip is None


def test_issue_diff_enabled_still_requires_base_sha(tmp_path: Path) -> None:
    policy_cls, runner_error_cls, build_artifacts, _cleanup = _import_am_patch()
    logger = _FakeLogger()
    paths = _paths(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    log_path = paths.logs_dir / "run.log"
    log_path.write_text("log\n", encoding="utf-8")

    policy = policy_cls()
    policy.success_archive_enabled = False
    policy.issue_diff_bundle_enabled = True

    with pytest.raises(runner_error_cls) as excinfo:
        build_artifacts(
            logger=logger,
            cli=SimpleNamespace(issue_id=123),
            policy=policy,
            paths=paths,
            repo_root=repo_root,
            log_path=log_path,
            exit_code=0,
            unified_mode=False,
            patch_applied_successfully=True,
            archived_patch=None,
            failed_patch_blobs_for_zip=[],
            files_for_fail_zip=[],
            ws_repo_for_fail_zip=repo_root,
            issue_diff_base_sha=None,
            issue_diff_paths=["alpha.py"],
            ws_attempt=None,
            effective_target_repo_name="patchhub",
        )

    assert excinfo.value.stage == "POSTHOOK"
    assert excinfo.value.category == "DIFF"


def test_enabled_outputs_preserve_existing_success_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_cls, _runner_error, build_artifacts, _cleanup = _import_am_patch()
    logger = _FakeLogger()
    paths = _paths(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    log_path = paths.logs_dir / "am_patch_issue_123_20260101_010101.log"
    log_path.write_text("log\n", encoding="utf-8")

    from am_patch import artifacts as artifacts_mod

    archive_calls: list[Path] = []
    diff_calls: list[tuple[int, list[str]]] = []
    monkeypatch.setattr(artifacts_mod.git_ops, "current_branch", lambda *_args: "main")
    monkeypatch.setattr(artifacts_mod.git_ops, "head_commit_epoch_s", lambda *_args: 0)
    monkeypatch.setattr(
        artifacts_mod.git_ops,
        "format_epoch_utc_ts",
        lambda _epoch: "19700101_000000",
    )

    def _git_archive(_logger, _repo_root, output_path: Path, *, treeish: str) -> None:
        assert treeish == "HEAD"
        archive_calls.append(output_path)
        output_path.write_text("zip", encoding="utf-8")

    def _make_issue_diff_zip(**kwargs):
        diff_calls.append((kwargs["issue_id"], list(kwargs["files_to_promote"])))
        out = kwargs["artifacts_dir"] / "issue_123_diff.zip"
        out.write_text("diff", encoding="utf-8")
        return out

    monkeypatch.setattr(artifacts_mod.git_ops, "git_archive", _git_archive)
    monkeypatch.setattr(artifacts_mod, "collect_issue_logs", lambda **_kwargs: [log_path])
    monkeypatch.setattr(artifacts_mod, "make_issue_diff_zip", _make_issue_diff_zip)

    policy = policy_cls()
    policy.success_archive_enabled = True
    policy.issue_diff_bundle_enabled = True
    policy.success_archive_name = "{repo}-{branch}_{issue}.zip"

    summary = build_artifacts(
        logger=logger,
        cli=SimpleNamespace(issue_id=123),
        policy=policy,
        paths=paths,
        repo_root=repo_root,
        log_path=log_path,
        exit_code=0,
        unified_mode=False,
        patch_applied_successfully=True,
        archived_patch=None,
        failed_patch_blobs_for_zip=[],
        files_for_fail_zip=[],
        ws_repo_for_fail_zip=repo_root,
        issue_diff_base_sha="abc123",
        issue_diff_paths=["alpha.py"],
        ws_attempt=None,
        effective_target_repo_name="patchhub",
    )

    expected_zip = paths.patch_dir / "repo-main_123.zip"
    assert summary.success_zip == expected_zip
    assert archive_calls == [expected_zip]
    assert summary.issue_diff_zip == paths.artifacts_dir / "issue_123_diff.zip"
    assert diff_calls == [(123, ["alpha.py"])]
