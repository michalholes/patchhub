from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


class _Logger:
    def __init__(self) -> None:
        self.sections: list[str] = []
        self.lines: list[str] = []

    def section(self, name: str) -> None:
        self.sections.append(name)

    def line(self, text: str) -> None:
        self.lines.append(text)

    def run_logged(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ):
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return type(
            "R",
            (),
            {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr},
        )()


def _import_gate_badguys():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import am_patch.gate_badguys as mod

    return mod


def _import_run_gates():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.gates import run_gates

    return run_gates


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    (repo / "keep.txt").write_text("base keep\n", encoding="utf-8")
    (repo / "delete_me.txt").write_text("base delete\n", encoding="utf-8")
    (repo / "rename_old.txt").write_text("base rename old\n", encoding="utf-8")
    (repo / "untouched.txt").write_text("base untouched\n", encoding="utf-8")
    (repo / "badguys").mkdir()
    (repo / "badguys" / "config.toml").write_text(
        """[suite]
logs_dir = "patches/badguys_logs"
central_log_pattern = "patches/badguys_{run_id}.log"
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _write_fake_bwrap(tmp_path: Path, *, exit_code: int) -> Path:
    script = tmp_path / "fake_bwrap.py"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
repo_arg = None
for idx, item in enumerate(args):
    if item == '/repo' and idx >= 1:
        repo_arg = args[idx - 1]
        break
repo = Path(repo_arg)
payload = {
    'argv': args,
    'env': {
        'AM_BADGUYS_RUN_ID': os.environ.get('AM_BADGUYS_RUN_ID'),
        'AM_PATCH_BADGUYS_RUNNER_PYTHON': os.environ.get('AM_PATCH_BADGUYS_RUNNER_PYTHON'),
        'AM_BADGUYS_SUITE_JAIL_INNER': os.environ.get('AM_BADGUYS_SUITE_JAIL_INNER'),
    },
    'repo': str(repo),
    'files': {
        'keep': (repo / 'keep.txt').read_text(encoding='utf-8'),
        'delete_exists': (repo / 'delete_me.txt').exists(),
        'rename_old_exists': (repo / 'rename_old.txt').exists(),
        'rename_new': (repo / 'rename_new.txt').read_text(encoding='utf-8'),
        'untracked': (repo / 'untracked.txt').read_text(encoding='utf-8'),
        'untouched': (repo / 'untouched.txt').read_text(encoding='utf-8'),
    },
}
Path(os.environ['CAPTURE_FILE']).write_text(json.dumps(payload), encoding='utf-8')
raise SystemExit(int(os.environ['BWRAP_EXIT']))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_should_run_badguys_uses_mode_and_trigger_surface() -> None:
    mod = _import_gate_badguys()

    assert mod.should_run_badguys(
        decision_paths=["docs/readme.md"],
        mode="always",
        trigger_prefixes=["scripts/am_patch"],
        trigger_files=["scripts/am_patch.md"],
    ) == (True, "always")
    assert mod.should_run_badguys(
        decision_paths=["scripts/am_patch/core.py"],
        mode="auto",
        trigger_prefixes=["scripts/am_patch"],
        trigger_files=["scripts/am_patch.md"],
    ) == (True, "trigger_prefix")
    assert mod.should_run_badguys(
        decision_paths=["scripts/am_patch.md"],
        mode="auto",
        trigger_prefixes=["scripts/am_patch"],
        trigger_files=["scripts/am_patch.md"],
    ) == (True, "trigger_file")
    assert mod.should_run_badguys(
        decision_paths=["docs/readme.md"],
        mode="auto",
        trigger_prefixes=["scripts/am_patch"],
        trigger_files=["scripts/am_patch.md"],
    ) == (False, "no_matching_files")


def test_badguys_trigger_surface_is_loaded_from_shipped_config() -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.config import Policy, build_policy, load_config

    cfg, used = load_config(scripts_dir / "am_patch" / "am_patch.toml")
    policy = build_policy(Policy(), cfg)

    assert used is True
    assert Policy().gate_badguys_trigger_prefixes == []
    assert Policy().gate_badguys_trigger_files == []
    assert policy.gate_badguys_trigger_prefixes == ["scripts/am_patch"]
    assert policy.gate_badguys_trigger_files == [
        "scripts/am_patch.py",
        "scripts/am_patch.md",
        "scripts/am_patch_specification.md",
        "scripts/am_patch_instructions.md",
    ]


@pytest.mark.parametrize("exit_code", [0, 1])
def test_amp_owned_badguys_gate_materializes_delta_env_and_cleans_jail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exit_code: int
) -> None:
    mod = _import_gate_badguys()
    repo = _init_repo(tmp_path)
    logger = _Logger()
    workspaces_dir = tmp_path / "patches" / "workspaces"
    capture_file = tmp_path / "capture.json"
    fake_bwrap = _write_fake_bwrap(tmp_path, exit_code=exit_code)

    (repo / ".venv" / "bin").mkdir(parents=True)
    fake_python = repo / ".venv" / "bin" / "python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    (repo / "keep.txt").write_text("live keep\n", encoding="utf-8")
    (repo / "delete_me.txt").unlink()
    (repo / "rename_old.txt").rename(repo / "rename_new.txt")
    (repo / "rename_new.txt").write_text("live rename new\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("live untracked\n", encoding="utf-8")
    (repo / "untouched.txt").write_text("live untouched\n", encoding="utf-8")

    monkeypatch.setattr(mod, "find_bwrap", lambda: str(fake_bwrap))
    monkeypatch.setattr(mod.sys, "executable", str(fake_python))
    changed_entries = [
        (" M", "keep.txt"),
        (" D", "delete_me.txt"),
        (" R", "rename_old.txt"),
        (" R", "rename_new.txt"),
        ("??", "untracked.txt"),
    ]
    monkeypatch.setattr(
        mod,
        "changed_path_entries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected recompute")),
        raising=False,
    )
    monkeypatch.setenv("CAPTURE_FILE", str(capture_file))
    monkeypatch.setenv("BWRAP_EXIT", str(exit_code))

    ok = mod.run_amp_owned_badguys_gate(
        logger,
        repo,
        repo_root=repo,
        command=["badguys/badguys.py", "-q"],
        changed_entries=changed_entries,
        workspaces_dir=workspaces_dir,
        cli_mode="workspace",
        issue_id="372",
    )

    assert ok is (exit_code == 0)
    payload = json.loads(capture_file.read_text(encoding="utf-8"))
    inner = payload["argv"][payload["argv"].index("--") + 1 :]
    assert inner.count("--no-suite-jail") == 1
    assert payload["env"]["AM_BADGUYS_RUN_ID"]
    assert payload["env"]["AM_BADGUYS_SUITE_JAIL_INNER"] == "1"
    assert payload["env"]["AM_PATCH_BADGUYS_RUNNER_PYTHON"] == "/repo/.venv/bin/python"
    assert payload["files"]["keep"] == "live keep\n"
    assert payload["files"]["delete_exists"] is False
    assert payload["files"]["rename_old_exists"] is False
    assert payload["files"]["rename_new"] == "live rename new\n"
    assert payload["files"]["untracked"] == "live untracked\n"
    assert payload["files"]["untouched"] == "base untouched\n"
    assert not (workspaces_dir / "_badguys_gate" / "workspace_372").exists()


def test_run_gates_api_keeps_skip_badguys_backward_compat(tmp_path: Path) -> None:
    run_gates = _import_run_gates()

    class DummyLogger:
        def warning_core(self, _msg: str) -> None:
            return None

        def error_core(self, _msg: str) -> None:
            return None

        def section(self, _msg: str) -> None:
            raise AssertionError("all gates must stay skipped")

        def line(self, _msg: str) -> None:
            raise AssertionError("all gates must stay skipped")

        def run_logged(self, _argv: list[str], *, cwd: Path, env=None):
            raise AssertionError("all gates must stay skipped")

    run_gates(
        DummyLogger(),  # type: ignore[arg-type]
        cwd=tmp_path,
        repo_root=tmp_path,
        run_all=False,
        compile_check=False,
        compile_targets=["."],
        compile_exclude=[],
        allow_fail=False,
        skip_dont_touch=True,
        dont_touch_paths=[],
        skip_ruff=True,
        skip_js=True,
        skip_biome=True,
        skip_typescript=True,
        skip_pytest=True,
        skip_mypy=True,
        skip_docs=True,
        skip_monolith=True,
        gate_monolith_enabled=False,
        gate_monolith_mode="strict",
        gate_monolith_scan_scope="patch",
        gate_monolith_compute_fanin=False,
        gate_monolith_on_parse_error="fail",
        gate_monolith_areas_prefixes=[],
        gate_monolith_areas_names=[],
        gate_monolith_areas_dynamic=[],
        gate_monolith_large_loc=900,
        gate_monolith_huge_loc=1300,
        gate_monolith_large_allow_loc_increase=20,
        gate_monolith_huge_allow_loc_increase=0,
        gate_monolith_large_allow_exports_delta=2,
        gate_monolith_huge_allow_exports_delta=0,
        gate_monolith_large_allow_imports_delta=1,
        gate_monolith_huge_allow_imports_delta=0,
        gate_monolith_new_file_max_loc=400,
        gate_monolith_new_file_max_exports=25,
        gate_monolith_new_file_max_imports=15,
        gate_monolith_hub_fanin_delta=5,
        gate_monolith_hub_fanout_delta=5,
        gate_monolith_hub_exports_delta_min=3,
        gate_monolith_hub_loc_delta_min=100,
        gate_monolith_crossarea_min_distinct_areas=3,
        gate_monolith_catchall_basenames=[],
        gate_monolith_catchall_dirs=[],
        gate_monolith_catchall_allowlist=[],
        docs_include=[],
        docs_exclude=[],
        docs_required_files=[],
        js_extensions=[".js"],
        js_command=["node", "--check"],
        biome_extensions=[],
        biome_command=[],
        biome_format=False,
        biome_format_command=[],
        biome_autofix=False,
        biome_fix_command=[],
        typescript_extensions=[],
        typescript_command=[],
        gate_typescript_mode="auto",
        typescript_targets=[],
        gate_typescript_base_tsconfig="tsconfig.json",
        ruff_format=False,
        ruff_autofix=False,
        ruff_targets=[],
        pytest_targets=[],
        mypy_targets=[],
        gate_ruff_mode="always",
        gate_mypy_mode="always",
        gate_pytest_mode="always",
        gate_pytest_js_prefixes=[],
        gates_order=["badguys"],
        pytest_use_venv=False,
        decision_paths=[],
        progress=None,
    )
