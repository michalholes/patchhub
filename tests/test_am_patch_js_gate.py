from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _import_gate():
    from am_patch.gates import check_js_gate

    return check_js_gate


def test_js_gate_not_triggered_when_no_js_touched() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["src/a.py", "docs/specification.md"],
        extensions=[".js"],
    )
    assert triggered is False
    assert js_paths == []


def test_js_gate_triggers_and_sorts_paths() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["b.js", "a.js", "src/x.py", "plugins/p.mjs"],
        extensions=[".js", ".mjs"],
    )
    assert triggered is True
    assert js_paths == ["a.js", "b.js", "plugins/p.mjs"]


def test_js_gate_respects_extensions_filter() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["a.mjs", "b.js"],
        extensions=[".js"],
    )
    assert triggered is True
    assert js_paths == ["b.js"]


def test_js_gate_handles_extension_without_dot() -> None:
    check_js_gate = _import_gate()
    triggered, js_paths = check_js_gate(
        ["a.JS", "b.txt"],
        extensions=["js"],
    )
    assert triggered is True
    assert js_paths == ["a.JS"]


def _import_run_gate():
    from am_patch.gates import run_js_syntax_gate

    return run_js_syntax_gate


def test_js_syntax_gate_skips_when_only_deleted_js_is_touched(tmp_path: Path) -> None:
    run_js_syntax_gate = _import_run_gate()

    class DummyLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning_core(self, msg: str) -> None:
            self.warnings.append(msg)

        def section(self, _msg: str) -> None:
            raise AssertionError("section() must not be called when JS gate is SKIP")

        def line(self, _msg: str) -> None:
            raise AssertionError("line() must not be called when JS gate is SKIP")

        def run_logged(self, _argv: list[str], *, cwd: Path):
            raise AssertionError("run_logged() must not be called when JS gate is SKIP")

    logger = DummyLogger()
    ok = run_js_syntax_gate(
        logger,  # type: ignore[arg-type]
        tmp_path,
        decision_paths=["deleted.js"],
        extensions=[".js"],
        command=["node", "--check"],
    )
    assert ok is True
    assert logger.warnings == ["gate_js=SKIP (no_existing_js_files)"]


def _import_run_gates():
    from am_patch.gates import run_gates

    return run_gates


def test_pytest_js_prefixes_still_trigger_pytest_gate(tmp_path: Path, monkeypatch) -> None:
    run_gates = _import_run_gates()

    captured: dict[str, object] = {}

    def fake_run_pytest(
        _logger,
        _cwd,
        *,
        repo_root: Path,
        pytest_use_venv: bool,
        targets: list[str],
    ):
        captured["repo_root"] = repo_root
        captured["pytest_use_venv"] = pytest_use_venv
        captured["targets"] = targets
        return True

    monkeypatch.setattr("am_patch.gates.run_pytest", fake_run_pytest)

    class DummyLogger:
        def warning_core(self, _msg: str) -> None:
            return None

        def error_core(self, _msg: str) -> None:
            raise AssertionError("pytest gate should not fail")

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
        skip_pytest=False,
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
        pytest_targets=["tests/legacy_target.py"],
        mypy_targets=[],
        gate_ruff_mode="always",
        gate_mypy_mode="always",
        gate_pytest_mode="auto",
        gate_pytest_py_prefixes=[],
        gate_pytest_js_prefixes=["scripts/patchhub/static"],
        pytest_routing_policy={"pytest_routing_mode": "legacy"},
        gates_order=["pytest"],
        pytest_use_venv=False,
        decision_paths=["scripts/patchhub/static/app.js"],
        progress=None,
    )

    assert captured["pytest_use_venv"] is False
    assert captured["targets"] == ["tests/legacy_target.py"]


def _import_run_pytest():
    from am_patch.gates import run_pytest

    return run_pytest


def _import_runner_error():
    from am_patch.errors import RunnerError

    return RunnerError


def test_run_pytest_rejects_empty_effective_target_list(tmp_path: Path) -> None:
    run_pytest = _import_run_pytest()
    runner_error = _import_runner_error()

    class DummyLogger:
        def section(self, _msg: str) -> None:
            raise AssertionError("section() must not be called for empty targets")

        def line(self, _msg: str) -> None:
            raise AssertionError("line() must not be called for empty targets")

        def run_logged(self, _argv: list[str], *, cwd: Path, env=None):
            raise AssertionError("run_logged() must not be called for empty targets")

    try:
        run_pytest(
            DummyLogger(),  # type: ignore[arg-type]
            tmp_path,
            repo_root=tmp_path,
            pytest_use_venv=False,
            targets=[],
        )
    except runner_error as exc:
        assert exc.stage == "CONFIG"
        assert exc.category == "PYTEST_TARGETS_EMPTY"
        assert exc.message == "effective pytest target list is empty"
    else:
        raise AssertionError("RunnerError was not raised for empty pytest targets")


def test_pytest_py_prefixes_trigger_pytest_gate(tmp_path: Path, monkeypatch) -> None:
    run_gates = _import_run_gates()

    captured: dict[str, object] = {}

    def fake_run_pytest(
        _logger,
        _cwd,
        *,
        repo_root: Path,
        pytest_use_venv: bool,
        targets: list[str],
    ):
        captured["repo_root"] = repo_root
        captured["pytest_use_venv"] = pytest_use_venv
        captured["targets"] = targets
        return True

    monkeypatch.setattr("am_patch.gates.run_pytest", fake_run_pytest)

    class DummyLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning_core(self, msg: str) -> None:
            self.warnings.append(msg)

        def error_core(self, _msg: str) -> None:
            raise AssertionError("pytest gate should not fail")

        def section(self, _msg: str) -> None:
            return None

        def line(self, _msg: str) -> None:
            return None

        def run_logged(self, _argv: list[str], *, cwd: Path, env=None):
            raise AssertionError("run_logged() must not be called in this test")

    logger = DummyLogger()
    run_gates(
        logger,  # type: ignore[arg-type]
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
        skip_pytest=False,
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
        pytest_targets=["tests/legacy_target.py"],
        mypy_targets=[],
        gate_ruff_mode="always",
        gate_mypy_mode="always",
        gate_pytest_mode="auto",
        gate_pytest_py_prefixes=["badguys"],
        gate_pytest_js_prefixes=[],
        pytest_routing_policy={"pytest_routing_mode": "legacy"},
        gates_order=["pytest"],
        pytest_use_venv=False,
        decision_paths=["badguys/bdg_executor.py"],
        progress=None,
    )

    assert captured["pytest_use_venv"] is False
    assert captured["targets"] == ["tests/legacy_target.py"]
    assert "gate_pytest=SKIP (no_matching_files)" not in logger.warnings


def test_pytest_py_prefixes_skip_when_no_matching_python_change(tmp_path: Path) -> None:
    run_gates = _import_run_gates()

    class DummyLogger:
        def __init__(self) -> None:
            self.warnings: list[str] = []

        def warning_core(self, msg: str) -> None:
            self.warnings.append(msg)

        def error_core(self, _msg: str) -> None:
            raise AssertionError("pytest gate should not fail")

        def section(self, _msg: str) -> None:
            return None

        def line(self, _msg: str) -> None:
            return None

        def run_logged(self, _argv: list[str], *, cwd: Path, env=None):
            raise AssertionError("run_logged() must not be called when pytest gate is SKIP")

    logger = DummyLogger()
    run_gates(
        logger,  # type: ignore[arg-type]
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
        skip_pytest=False,
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
        pytest_targets=["tests/legacy_target.py"],
        mypy_targets=[],
        gate_ruff_mode="always",
        gate_mypy_mode="always",
        gate_pytest_mode="auto",
        gate_pytest_py_prefixes=["badguys"],
        gate_pytest_js_prefixes=[],
        pytest_routing_policy={"pytest_routing_mode": "legacy"},
        gates_order=["pytest"],
        pytest_use_venv=False,
        decision_paths=["plugins/import/service.py"],
        progress=None,
    )

    assert logger.warnings[-1] == "gate_pytest=SKIP (no_matching_files)"
    assert logger.warnings.count("gate_pytest=SKIP (no_matching_files)") == 1
