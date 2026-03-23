from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from am_patch.errors import RunnerError
from am_patch.gate_badguys import configure_badguys_runtime, run_badguys_gate


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.warnings: list[str] = []

    def section(self, message: str) -> None:
        self.lines.append(message)

    def line(self, message: str) -> None:
        self.lines.append(message)

    def warning_core(self, message: str) -> None:
        self.warnings.append(message)

    def error_core(self, message: str) -> None:
        self.lines.append(message)

    def run_logged(self, argv, cwd=None, env=None, **_kwargs):
        return subprocess.run(
            argv,
            cwd=None if cwd is None else str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "badguys").mkdir(parents=True)
    (root / "scripts" / "am_patch").mkdir(parents=True)
    (root / "patches").mkdir()
    (root / "badguys" / "config.toml").write_text(
        '[suite]\nlogs_dir = "patches/badguys_logs"\n'
        'central_log_pattern = "patches/badguys_{run_id}.log"\n',
        encoding="utf-8",
    )
    (root / "scripts" / "am_patch" / "engine.py").write_text("print('base')\n", encoding="utf-8")
    (root / "rename_old.txt").write_text("old\n", encoding="utf-8")
    (root / "delete_me.txt").write_text("delete\n", encoding="utf-8")
    (root / "untouched.txt").write_text("untouched\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
    return root


def _configure(repo: Path, *, issue_id: str = "372") -> None:
    configure_badguys_runtime(
        workspaces_dir=repo / "patches" / "workspaces",
        cli_mode="workspace",
        issue_id=issue_id,
    )


def test_badguys_gate_auto_skip_and_always_mode(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(repo)
    logger = _Logger()
    calls: list[list[str]] = []

    def fake_run(*_args, command: list[str], **_kwargs) -> bool:
        calls.append(list(command))
        return True

    monkeypatch.setattr("am_patch.gate_badguys._run_badguys_in_jail", fake_run)

    ok = run_badguys_gate(
        logger,
        repo,
        repo_root=repo,
        decision_paths=["docs/readme.md"],
        skip_badguys=False,
        gate_badguys_mode="auto",
        gate_badguys_trigger_prefixes=["scripts/am_patch"],
        gate_badguys_trigger_files=["scripts/am_patch.md"],
        gate_badguys_command=["badguys/badguys.py", "-q"],
    )
    assert ok is True
    assert calls == []
    assert logger.warnings[-1] == "gate_badguys=SKIP (no_matching_files)"

    ok = run_badguys_gate(
        logger,
        repo,
        repo_root=repo,
        decision_paths=["docs/readme.md"],
        skip_badguys=False,
        gate_badguys_mode="always",
        gate_badguys_trigger_prefixes=["scripts/am_patch"],
        gate_badguys_trigger_files=["scripts/am_patch.md"],
        gate_badguys_command=["badguys/badguys.py", "-q"],
    )
    assert ok is True
    assert calls == [["badguys/badguys.py", "-q", "--no-suite-jail"]]


def test_badguys_gate_materializes_delta_and_sets_env(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(repo)
    logger = _Logger()
    (repo / "scripts" / "am_patch" / "engine.py").write_text("print('changed')\n", encoding="utf-8")
    subprocess.run(["git", "mv", "rename_old.txt", "rename_new.txt"], cwd=repo, check=True)
    (repo / "rename_new.txt").write_text("renamed\n", encoding="utf-8")
    subprocess.run(["git", "rm", "-q", "delete_me.txt"], cwd=repo, check=True)
    (repo / "added.txt").write_text("added\n", encoding="utf-8")

    copied: list[str] = []
    original_materialize = __import__(
        "am_patch.gate_badguys",
        fromlist=["_materialize_path"],
    )._materialize_path

    def recording_materialize(
        *,
        source_repo_root: Path,
        jail_repo_root: Path,
        relpath: str,
    ) -> None:
        copied.append(relpath)
        original_materialize(
            source_repo_root=source_repo_root,
            jail_repo_root=jail_repo_root,
            relpath=relpath,
        )

    captured: dict[str, object] = {}

    def fake_run(
        *_args,
        jail_repo_root: Path,
        command: list[str],
        env: dict[str, str],
        **_kwargs,
    ) -> bool:
        captured["jail_root"] = jail_repo_root.parent
        captured["command"] = list(command)
        captured["env"] = dict(env)
        engine_text = (jail_repo_root / "scripts" / "am_patch" / "engine.py").read_text(
            encoding="utf-8"
        )
        assert engine_text == "print('changed')\n"
        assert (jail_repo_root / "rename_new.txt").read_text(encoding="utf-8") == "renamed\n"
        assert not (jail_repo_root / "rename_old.txt").exists()
        assert not (jail_repo_root / "delete_me.txt").exists()
        assert (jail_repo_root / "added.txt").read_text(encoding="utf-8") == "added\n"
        return True

    monkeypatch.setattr("am_patch.gate_badguys._materialize_path", recording_materialize)
    monkeypatch.setattr("am_patch.gate_badguys._run_badguys_in_jail", fake_run)

    ok = run_badguys_gate(
        logger,
        repo,
        repo_root=repo,
        decision_paths=["scripts/am_patch/engine.py"],
        skip_badguys=False,
        gate_badguys_mode="auto",
        gate_badguys_trigger_prefixes=["scripts/am_patch"],
        gate_badguys_trigger_files=["scripts/am_patch.md"],
        gate_badguys_command=["badguys/badguys.py", "-q"],
    )

    assert ok is True
    assert sorted(copied) == [
        "added.txt",
        "delete_me.txt",
        "rename_new.txt",
        "rename_old.txt",
        "scripts/am_patch/engine.py",
    ]
    assert "untouched.txt" not in copied
    assert captured["command"] == ["badguys/badguys.py", "-q", "--no-suite-jail"]
    env = captured["env"]
    assert env["AM_BADGUYS_RUN_ID"] == "workspace_372"
    assert env["AM_PATCH_BADGUYS_RUNNER_PYTHON"]
    assert not Path(captured["jail_root"]).exists()


def test_badguys_gate_cleans_jail_after_inner_failure(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(repo)
    logger = _Logger()
    (repo / "scripts" / "am_patch" / "engine.py").write_text("print('changed')\n", encoding="utf-8")
    captured: dict[str, Path] = {}

    def fake_run(*_args, jail_repo_root: Path, **_kwargs) -> bool:
        captured["jail_root"] = jail_repo_root.parent
        assert captured["jail_root"].exists()
        return False

    monkeypatch.setattr("am_patch.gate_badguys._run_badguys_in_jail", fake_run)

    ok = run_badguys_gate(
        logger,
        repo,
        repo_root=repo,
        decision_paths=["scripts/am_patch/engine.py"],
        skip_badguys=False,
        gate_badguys_mode="always",
        gate_badguys_trigger_prefixes=["scripts/am_patch"],
        gate_badguys_trigger_files=["scripts/am_patch.md"],
        gate_badguys_command=["badguys/badguys.py", "-q", "--no-suite-jail"],
    )

    assert ok is False
    assert not captured["jail_root"].exists()


def test_badguys_gate_uses_jail_visible_python_for_repo_local_interpreter(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from am_patch.gate_badguys import _build_jail_env, _run_badguys_in_jail

    local_python = repo / ".venv" / "bin" / "python"
    local_python.parent.mkdir(parents=True)
    local_python.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bwrap.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(local_python))
    monkeypatch.setenv("AM_PATCH_BWRAP", str(fake_bwrap))

    captured: dict[str, object] = {}

    class CaptureLogger:
        def run_logged(self, argv, cwd=None, env=None, **_kwargs):
            captured["argv"] = list(argv)
            captured["env"] = dict(env or {})
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    env = _build_jail_env(source_repo_root=repo, run_id="workspace_372")
    ok = _run_badguys_in_jail(
        CaptureLogger(),
        source_repo_root=repo,
        jail_repo_root=(
            repo / "patches" / "workspaces" / "_badguys_gate" / "workspace_372" / "repo"
        ),
        bind_targets=[],
        external_bind_paths=[],
        command=["badguys/badguys.py", "-q", "--no-suite-jail"],
        env=env,
    )

    assert ok is True
    argv = captured["argv"]
    pivot = argv.index("--")
    assert argv[0] == str(fake_bwrap)
    assert argv[pivot + 1 : pivot + 4] == ["/repo/.venv/bin/python", "-u", "badguys/badguys.py"]
    assert captured["env"]["AM_PATCH_BADGUYS_RUNNER_PYTHON"] == "/repo/.venv/bin/python"


def test_badguys_gate_respects_am_patch_bwrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from am_patch.gate_badguys import _build_bwrap_cmd

    fake_bwrap = tmp_path / "custom-bwrap"
    fake_bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("AM_PATCH_BWRAP", str(fake_bwrap))

    cmd = _build_bwrap_cmd(
        source_repo_root=tmp_path,
        jail_repo_root=tmp_path / "repo",
        bind_targets=[],
        external_bind_paths=[],
        argv=["python", "-u", "badguys/badguys.py", "-q", "--no-suite-jail"],
    )

    assert cmd[0] == str(fake_bwrap)


def test_badguys_gate_cleans_partial_jail_after_bootstrap_failure(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(repo)
    logger = _Logger()

    def fail_bootstrap(*_args, **_kwargs) -> None:
        raise RunnerError("GATES", "GATES", "bootstrap failed")

    monkeypatch.setattr("am_patch.gate_badguys._bootstrap_jail_repo", fail_bootstrap)
    jail_root = repo / "patches" / "workspaces" / "_badguys_gate" / "workspace_372"

    with pytest.raises(RunnerError):
        run_badguys_gate(
            logger,
            repo,
            repo_root=repo,
            decision_paths=["scripts/am_patch/engine.py"],
            skip_badguys=False,
            gate_badguys_mode="always",
            gate_badguys_trigger_prefixes=["scripts/am_patch"],
            gate_badguys_trigger_files=["scripts/am_patch.md"],
            gate_badguys_command=["badguys/badguys.py", "-q"],
        )

    assert not jail_root.exists()
