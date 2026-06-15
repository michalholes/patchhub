from __future__ import annotations

import sys
from pathlib import Path


def _import_mods():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.gate_pyright import should_run_pyright
    from am_patch.gates import run_gates

    return should_run_pyright, run_gates


def test_should_run_pyright_triggers_on_config_and_prefixes() -> None:
    should_run_pyright, _ = _import_mods()

    assert should_run_pyright(
        decision_paths=["pyrightconfig.json"],
        targets=["scripts", "badguys"],
    )
    assert should_run_pyright(
        decision_paths=["scripts/am_patch/config.py"],
        targets=["scripts", "badguys"],
    )
    assert not should_run_pyright(
        decision_paths=["docs/readme.md"],
        targets=["scripts", "badguys"],
    )


def test_run_gates_invokes_pyright_gate(monkeypatch, tmp_path: Path) -> None:
    _, run_gates = _import_mods()

    captured: dict[str, object] = {}

    def fake_run_pyright(
        _logger,
        _cwd,
        *,
        active_repository_tree_root: Path,
        python_gate_mode: str,
        python_gate_python: str,
    ) -> bool:
        captured["root"] = active_repository_tree_root
        captured["mode"] = python_gate_mode
        captured["python"] = python_gate_python
        return True

    monkeypatch.setattr("am_patch.gate_pyright.run_pyright", fake_run_pyright)

    class DummyLogger:
        def warning_core(self, _msg: str) -> None:
            return None

        def error_core(self, _msg: str) -> None:
            raise AssertionError("pyright gate should not fail")

        def section(self, _msg: str) -> None:
            return None

        def line(self, _msg: str) -> None:
            return None

        def run_logged(self, _argv: list[str], *, cwd: Path, env=None):
            raise AssertionError("run_logged() must not be called in this test")

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
        gate_pyright_mode="always",
        gate_pytest_mode="always",
        gate_pytest_py_prefixes=[],
        gate_pytest_js_prefixes=[],
        pytest_routing_policy={"pytest_routing_mode": "legacy"},
        gates_order=["pyright"],
        pytest_use_venv=False,
        pyright_targets=["scripts", "badguys"],
        skip_pyright=False,
        active_repository_tree_root=tmp_path,
        decision_paths=["pyrightconfig.json"],
        progress=None,
    )

    assert captured["root"] == tmp_path
    assert captured["mode"] == "auto"
    assert captured["python"] == ".venv/bin/python"
