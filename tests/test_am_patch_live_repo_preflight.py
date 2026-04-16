from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parents[1]
scripts_dir = repo_root / "scripts"
sys.path.insert(0, str(scripts_dir))

from am_patch.errors import RunnerError  # noqa: E402
from am_patch.git_ops import current_branch, head_sha, live_repo_preflight  # noqa: E402


class _RunResult:
    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _Logger:
    def run_logged(self, argv, *, cwd: Path, timeout_stage: str, env=None):
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
        )
        return _RunResult(result.stdout, result.stderr, result.returncode)


class _FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sections: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)


class _FakeLock:
    def __init__(self, _path: Path) -> None:
        self.acquired = 0

    def acquire(self) -> None:
        self.acquired += 1


def _run(argv: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _clone(repo: Path, target: Path, *, branch: str | None = None) -> None:
    argv = ["git", "clone"]
    if branch is not None:
        argv.extend(["-b", branch])
    argv.extend([str(repo), str(target)])
    _run(argv, cwd=target.parent)
    _run(["git", "config", "user.email", "test@example.com"], cwd=target)
    _run(["git", "config", "user.name", "Test"], cwd=target)


def _commit(repo: Path, relpath: str, body: str, message: str) -> str:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _run(["git", "add", relpath], cwd=repo)
    _run(["git", "commit", "-m", message], cwd=repo)
    return _run(["git", "rev-parse", "HEAD"], cwd=repo).strip()


def _push(repo: Path, branch: str) -> None:
    _run(["git", "push", "-u", "origin", branch], cwd=repo)


def _prepare_remote_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    local = tmp_path / "local"
    other = tmp_path / "other"
    origin.mkdir(parents=True)
    _run(["git", "init", "--bare"], cwd=origin)
    _clone(origin, local)
    _run(["git", "checkout", "-b", "main"], cwd=local)
    _commit(local, "keep.txt", "base\n", "base")
    _push(local, "main")
    _clone(origin, other, branch="main")
    return origin, local, other


def test_live_repo_preflight_auto_pull_updates_fast_forward(tmp_path: Path) -> None:
    _origin, local, other = _prepare_remote_pair(tmp_path)
    remote_sha = _commit(other, "keep.txt", "remote\n", "remote")
    _push(other, "main")

    logger = _Logger()
    live_repo_preflight(
        logger,
        local,
        default_branch="main",
        require_up_to_date_flag=True,
        skip_up_to_date=False,
        enforce_main_branch=False,
        allow_non_main=False,
        auto_pull_if_behind=True,
    )

    assert head_sha(logger, local) == remote_sha
    assert current_branch(logger, local) == "main"
    assert (local / "keep.txt").read_text(encoding="utf-8") == "remote\n"


def test_live_repo_preflight_auto_pull_updates_local_default_branch_only(
    tmp_path: Path,
) -> None:
    _origin, local, other = _prepare_remote_pair(tmp_path)
    _run(["git", "checkout", "-b", "feature"], cwd=local)
    feature_sha_before = _run(["git", "rev-parse", "HEAD"], cwd=local).strip()
    remote_sha = _commit(other, "keep.txt", "remote\n", "remote")
    _push(other, "main")

    logger = _Logger()
    live_repo_preflight(
        logger,
        local,
        default_branch="main",
        require_up_to_date_flag=True,
        skip_up_to_date=False,
        enforce_main_branch=True,
        allow_non_main=True,
        auto_pull_if_behind=True,
    )

    assert current_branch(logger, local) == "feature"
    assert head_sha(logger, local) == feature_sha_before
    assert _run(["git", "rev-parse", "main"], cwd=local).strip() == remote_sha
    assert (local / "keep.txt").read_text(encoding="utf-8") == "base\n"


def test_live_repo_preflight_disabled_auto_pull_fails_closed(tmp_path: Path) -> None:
    _origin, local, other = _prepare_remote_pair(tmp_path)
    _commit(other, "keep.txt", "remote\n", "remote")
    _push(other, "main")

    logger = _Logger()
    with pytest.raises(RunnerError, match=r"origin/main is ahead by 1 commits"):
        live_repo_preflight(
            logger,
            local,
            default_branch="main",
            require_up_to_date_flag=True,
            skip_up_to_date=False,
            enforce_main_branch=False,
            allow_non_main=False,
            auto_pull_if_behind=False,
        )


def test_live_repo_preflight_non_fast_forward_fails_closed(tmp_path: Path) -> None:
    _origin, local, other = _prepare_remote_pair(tmp_path)
    _commit(local, "local.txt", "local\n", "local")
    _commit(other, "keep.txt", "remote\n", "remote")
    _push(other, "main")

    logger = _Logger()
    local_sha_before = head_sha(logger, local)
    with pytest.raises(RunnerError, match=r"fast-forward-only update from origin/main failed"):
        live_repo_preflight(
            logger,
            local,
            default_branch="main",
            require_up_to_date_flag=True,
            skip_up_to_date=False,
            enforce_main_branch=False,
            allow_non_main=False,
            auto_pull_if_behind=True,
        )

    assert head_sha(logger, local) == local_sha_before


def test_live_repo_preflight_checks_branch_before_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import am_patch.git_ops as git_ops_mod

    order: list[str] = []

    monkeypatch.setattr(
        git_ops_mod,
        "require_branch",
        lambda *args, **kwargs: order.append("branch"),
    )
    monkeypatch.setattr(git_ops_mod, "fetch", lambda *args, **kwargs: order.append("fetch"))
    monkeypatch.setattr(git_ops_mod, "origin_ahead_count", lambda *args, **kwargs: 0)

    live_repo_preflight(
        _Logger(),
        tmp_path,
        default_branch="main",
        require_up_to_date_flag=True,
        skip_up_to_date=False,
        enforce_main_branch=True,
        allow_non_main=False,
        auto_pull_if_behind=True,
    )

    assert order == ["branch", "fetch"]


def test_finalize_mode_uses_shared_live_repo_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import am_patch.engine as engine_mod

    policy = engine_mod.Policy()
    policy.audit_rubric_guard = False
    policy.live_repo_guard = False
    policy.commit_and_push = False
    policy.require_up_to_date = True
    policy.skip_up_to_date = False
    policy.enforce_main_branch = True
    policy.allow_non_main = False
    policy.auto_pull_if_behind = True

    patch_root = tmp_path / "patches"
    patch_dir = patch_root / "incoming"
    patch_dir.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    paths = SimpleNamespace(
        lock_path=patch_root / ".am_patch.lock",
        symlink_path=patch_root / "current.log",
        successful_dir=patch_root / "successful",
        unsuccessful_dir=patch_root / "unsuccessful",
        workspaces_dir=patch_root / "workspaces",
        logs_dir=patch_root / "logs",
        artifacts_dir=patch_root / "artifacts",
    )
    ctx = engine_mod.RunContext(
        cli=SimpleNamespace(mode="finalize", message="finalize", issue_id=None, patch_script=None),
        policy=policy,
        config_path=tmp_path / "am_patch.toml",
        used_cfg="cfg",
        repo_root=repo,
        patch_root=patch_root,
        patch_dir=patch_dir,
        isolated_work_patch_dir=None,
        paths=paths,
        log_path=patch_root / "logs" / "run.log",
        json_path=None,
        logger=_FakeLogger(),
        status=SimpleNamespace(stop=lambda: None),
        verbosity="normal",
        log_level="normal",
        ipc=None,
        runner_root=tmp_path,
        artifacts_root=patch_root,
        active_repository_tree_root=repo,
        live_target_root=repo,
        effective_target_repo_name="patchhub",
        preopened_workspace=None,
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(engine_mod, "FileLock", _FakeLock)
    monkeypatch.setattr(engine_mod, "policy_for_log", lambda policy: "policy")
    monkeypatch.setattr(
        engine_mod.git_ops,
        "fetch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("inline fetch forbidden")),
    )
    monkeypatch.setattr(
        engine_mod.git_ops,
        "require_up_to_date",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("inline require_up_to_date forbidden")
        ),
    )
    monkeypatch.setattr(
        engine_mod.git_ops,
        "require_branch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("inline require_branch forbidden")
        ),
    )
    monkeypatch.setattr(
        engine_mod.git_ops,
        "live_repo_preflight",
        lambda _logger, repo_root, **kwargs: calls.append({"repo": repo_root, **kwargs}),
    )
    monkeypatch.setattr(engine_mod.git_ops, "head_sha", lambda *args, **kwargs: "base-sha")
    monkeypatch.setattr(engine_mod, "changed_paths", lambda *args, **kwargs: [])
    monkeypatch.setattr(engine_mod, "run_finalize_gates", lambda **kwargs: None)

    result = engine_mod.run_mode(ctx)

    assert result.exit_code == 0
    assert calls == [
        {
            "repo": repo,
            "default_branch": "main",
            "require_up_to_date_flag": True,
            "skip_up_to_date": False,
            "enforce_main_branch": True,
            "allow_non_main": False,
            "auto_pull_if_behind": True,
        }
    ]
