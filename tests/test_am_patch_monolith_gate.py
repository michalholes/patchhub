from __future__ import annotations

import sys
from pathlib import Path


def _import_monolith_gate():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy, apply_cli_overrides
    from am_patch.gates import run_gates
    from am_patch.log import Logger
    from am_patch.monolith_gate import run_monolith_gate

    return Logger, run_monolith_gate, Policy, apply_cli_overrides, run_gates


def _make_logger(tmp_path: Path):
    logger_cls, *_ = _import_monolith_gate()
    log_path = tmp_path / "log.txt"
    symlink_path = tmp_path / "current.log"
    return logger_cls(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level="quiet",
        log_level="debug",
        console_color="never",
        symlink_enabled=False,
    )


def _write_file(root: Path, rel: Path, text: str) -> None:
    (root / rel.parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _read_log(tmp_path: Path) -> str:
    return (tmp_path / "log.txt").read_text(encoding="utf-8")


def _default_area_lists():
    # Keep this in sync with scripts/am_patch/am_patch.toml defaults.
    prefixes = [
        "src/audiomason/",
        "scripts/am_patch/",
        "plugins/",
        "tests/",
        "scripts/",
    ]
    names = [
        "core",
        "runner",
        "plugins",
        "tests",
        "tooling",
    ]
    dynamic = [
        "",
        "",
        "plugins.<name>",
        "",
        "",
    ]
    return prefixes, names, dynamic


def test_monolith_catchall_new_file_fails_and_allowlist_passes(tmp_path: Path) -> None:
    logger_cls, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("src/audiomason/utils.py")
    _write_file(cwd, rel, "def ok():\n    return 1\n")

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            gate_monolith_catchall_basenames=["utils.py"],
            gate_monolith_catchall_dirs=["utils"],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok is False
        assert "MONO.CATCHALL" in _read_log(tmp_path)

        # Allowlisted relpath must pass.
        logger.close()
        logger = _make_logger(tmp_path)
        ok2 = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            gate_monolith_catchall_basenames=["utils.py"],
            gate_monolith_catchall_dirs=["utils"],
            gate_monolith_catchall_allowlist=[str(rel)],
        )
        assert ok2 is True
        assert "MONOLITH: PASS" in _read_log(tmp_path)
    finally:
        logger.close()


def test_monolith_verbose_stats_emitted_on_pass(tmp_path: Path) -> None:
    _, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("src/audiomason/ok_module.py")
    text = "def ok():\n    return 1\n"
    _write_file(repo_root, rel, text)
    _write_file(cwd, rel, text)

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            gate_monolith_hub_fanin_delta=999,
            gate_monolith_hub_fanout_delta=999,
            gate_monolith_hub_exports_delta_min=999,
            gate_monolith_hub_loc_delta_min=999,
            gate_monolith_crossarea_min_distinct_areas=999,
            gate_monolith_catchall_basenames=["utils.py"],
            gate_monolith_catchall_dirs=["utils"],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok is True

        log = _read_log(tmp_path)
        assert "MONOLITH: PASS" in log
        assert "gate_monolith_files_scanned=" in log
        assert "gate_monolith_loc_total_old=" in log
        assert "gate_monolith_loc_total_new=" in log
        assert "gate_monolith_fanin_delta_max=n/a" in log
        assert "gate_monolith_fanout_delta_max=n/a" in log
    finally:
        logger.close()


def test_monolith_parse_error_severity_by_mode(tmp_path: Path) -> None:
    logger_cls, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("scripts/am_patch/bad.py")
    _write_file(repo_root, rel, "x = 1\n")
    _write_file(cwd, rel, "def oops(:\n    return 1\n")

    # warn_only + on_parse_error=fail -> FAIL
    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="warn_only",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
        )
        assert ok is False
        assert "MONO.PARSE" in _read_log(tmp_path)
    finally:
        logger.close()

    # report_only + on_parse_error=fail -> WARN (no fail)
    logger = _make_logger(tmp_path)
    try:
        ok2 = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="report_only",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
        )
        assert ok2 is True
        assert "MONOLITH: WARN" in _read_log(tmp_path)
    finally:
        logger.close()

    # warn_only + on_parse_error=warn -> WARN (no fail)
    logger = _make_logger(tmp_path)
    try:
        ok3 = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="warn_only",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="warn",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
        )
        assert ok3 is True
        assert "MONOLITH: WARN" in _read_log(tmp_path)
    finally:
        logger.close()


def test_monolith_new_file_thresholds_loc_exports_imports(tmp_path: Path) -> None:
    logger_cls, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("scripts/am_patch/new_big.py")

    many_defs = "\n".join([f"def f{i}():\n    return {i}\n" for i in range(30)])
    filler = "\n".join(["x = 1" for _ in range(401)])
    text = filler + "\n" + many_defs + "\n" + "import plugins.foo\nimport plugins.bar\n"
    _write_file(cwd, rel, text)

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            gate_monolith_new_file_max_imports=1,
            gate_monolith_hub_fanin_delta=5,
            gate_monolith_hub_fanout_delta=5,
            gate_monolith_hub_exports_delta_min=3,
            gate_monolith_hub_loc_delta_min=100,
            gate_monolith_crossarea_min_distinct_areas=3,
            gate_monolith_catchall_basenames=[],
            gate_monolith_catchall_dirs=[],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok is False
        log = _read_log(tmp_path)
        assert "MONO.NEWFILE" in log
    finally:
        logger.close()


def test_monolith_skip_monolith_flag_is_wired(tmp_path: Path) -> None:
    logger_cls, _, policy_cls, apply_cli_overrides, run_gates = _import_monolith_gate()

    p = policy_cls()
    apply_cli_overrides(p, {"gates_skip_monolith": True})
    assert p.gates_skip_monolith is True

    # Validate gates layer: skip must not raise.
    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    logger = _make_logger(tmp_path)
    try:
        run_gates(
            logger,
            cwd,
            repo_root=repo_root,
            run_all=False,
            compile_check=False,
            compile_targets=[],
            compile_exclude=[],
            allow_fail=False,
            skip_ruff=True,
            skip_js=True,
            skip_pytest=True,
            skip_mypy=True,
            skip_docs=True,
            skip_monolith=True,
            gate_monolith_enabled=True,
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            js_extensions=[],
            js_command=[],
            biome_autofix=True,
            biome_fix_command=[],
            ruff_format=False,
            ruff_autofix=False,
            ruff_targets=[],
            pytest_targets=[],
            mypy_targets=[],
            gates_order=["monolith"],
            pytest_use_venv=False,
            decision_paths=[],
        )
        assert "gate_monolith=SKIP (skipped_by_user)" in _read_log(tmp_path)
    finally:
        logger.close()


def test_monolith_crossarea_warn_only_warns(tmp_path: Path) -> None:
    logger_cls, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("scripts/am_patch/cross.py")
    _write_file(repo_root, rel, "x = 1\n")
    _write_file(
        cwd,
        rel,
        "import audiomason.core\nimport plugins.foo\nimport tests.test_x\n\nx = 2\n",
    )

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="warn_only",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
        )
        assert ok is True
        log = _read_log(tmp_path)
        assert "MONO.CROSSAREA" in log
        assert "MONOLITH: WARN" in log
    finally:
        logger.close()


def test_monolith_growth_large_and_huge(tmp_path: Path) -> None:
    logger_cls, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    # LARGE: exports delta beyond allow.
    rel = Path("scripts/am_patch/large.py")
    filler = "\n".join(["x = 1" for _ in range(900)]) + "\n"
    old_text = filler + "def a():\n    return 1\n"
    new_text = filler + "\n".join(
        [
            "def a():\n    return 1\n",
            "def b():\n    return 2\n",
            "def c():\n    return 3\n",
            "def d():\n    return 4\n",
        ]
    )
    _write_file(repo_root, rel, old_text)
    _write_file(cwd, rel, new_text)

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
            gate_monolith_large_loc=900,
            gate_monolith_huge_loc=1300,
            gate_monolith_large_allow_loc_increase=999,
            gate_monolith_huge_allow_loc_increase=0,
            gate_monolith_large_allow_exports_delta=2,
            gate_monolith_huge_allow_exports_delta=0,
            gate_monolith_large_allow_imports_delta=1,
            gate_monolith_huge_allow_imports_delta=0,
            gate_monolith_new_file_max_loc=400,
            gate_monolith_new_file_max_exports=25,
            gate_monolith_new_file_max_imports=15,
            gate_monolith_hub_fanin_delta=999,
            gate_monolith_hub_fanout_delta=999,
            gate_monolith_hub_exports_delta_min=999,
            gate_monolith_hub_loc_delta_min=999,
            gate_monolith_crossarea_min_distinct_areas=999,
            gate_monolith_catchall_basenames=[],
            gate_monolith_catchall_dirs=[],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok is False
        assert "MONO.GROWTH" in _read_log(tmp_path)
    finally:
        logger.close()

    # HUGE: loc delta beyond allow.
    rel2 = Path("scripts/am_patch/huge.py")
    base = "\n".join(["x = 1" for _ in range(1300)]) + "\n"
    _write_file(repo_root, rel2, base)
    _write_file(cwd, rel2, base + "y = 2\n")

    logger = _make_logger(tmp_path)
    try:
        ok2 = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel2)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=_default_area_lists()[0],
            gate_monolith_areas_names=_default_area_lists()[1],
            gate_monolith_areas_dynamic=_default_area_lists()[2],
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
            gate_monolith_hub_fanin_delta=999,
            gate_monolith_hub_fanout_delta=999,
            gate_monolith_hub_exports_delta_min=999,
            gate_monolith_hub_loc_delta_min=999,
            gate_monolith_crossarea_min_distinct_areas=999,
            gate_monolith_catchall_basenames=[],
            gate_monolith_catchall_dirs=[],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok2 is False
        assert "MONO.GROWTH" in _read_log(tmp_path)
    finally:
        logger.close()


def test_monolith_legacy_key_rejected(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy, build_policy
    from am_patch.errors import RunnerError

    cfg: dict[str, object] = {
        "gate_monolith_areas": ["scripts/am_patch", "tests"],
    }

    try:
        build_policy(Policy(), cfg)  # type: ignore[arg-type]
        raise AssertionError("expected RunnerError")
    except RunnerError as e:
        assert e.stage == "CONFIG"
        assert e.category == "INVALID"
        assert "legacy config key is forbidden" in e.message


def test_monolith_areas_length_mismatch_rejected(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy, build_policy
    from am_patch.errors import RunnerError

    cfg: dict[str, object] = {
        "gate_monolith_areas_prefixes": ["scripts/am_patch", "tests"],
        "gate_monolith_areas_names": ["am_patch"],
        "gate_monolith_areas_dynamic": ["", ""],
    }

    try:
        build_policy(Policy(), cfg)  # type: ignore[arg-type]
        raise AssertionError("expected RunnerError")
    except RunnerError as e:
        assert e.stage == "CONFIG"
        assert e.category == "INVALID"
        assert "lengths mismatch" in e.message


def test_monolith_areas_empty_entry_rejected(tmp_path: Path) -> None:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.config import Policy, build_policy
    from am_patch.errors import RunnerError

    cfg: dict[str, object] = {
        "gate_monolith_areas_prefixes": ["", "tests"],
        "gate_monolith_areas_names": ["am_patch", "tests"],
        "gate_monolith_areas_dynamic": ["", ""],
    }

    try:
        build_policy(Policy(), cfg)  # type: ignore[arg-type]
        raise AssertionError("expected RunnerError")
    except RunnerError as e:
        assert e.stage == "CONFIG"
        assert e.category == "INVALID"
        assert "must be non-empty" in e.message


def test_monolith_default_area_mapping_parity(tmp_path: Path) -> None:
    _, run_monolith_gate, *_ = _import_monolith_gate()

    repo_root = tmp_path / "repo_root"
    cwd = tmp_path / "cwd"
    repo_root.mkdir()
    cwd.mkdir()

    rel = Path("plugins/example_pkg/mod.py")
    text = "def ok():\n    return 1\n"
    _write_file(repo_root, rel, text)
    _write_file(cwd, rel, text)

    prefixes, names, dynamic = _default_area_lists()

    logger = _make_logger(tmp_path)
    try:
        ok = run_monolith_gate(
            logger,
            cwd,
            repo_root=repo_root,
            decision_paths=[str(rel)],
            gate_monolith_mode="strict",
            gate_monolith_scan_scope="patch",
            gate_monolith_compute_fanin=False,
            gate_monolith_on_parse_error="fail",
            gate_monolith_areas_prefixes=prefixes,
            gate_monolith_areas_names=names,
            gate_monolith_areas_dynamic=dynamic,
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
            gate_monolith_hub_fanin_delta=999,
            gate_monolith_hub_fanout_delta=999,
            gate_monolith_hub_exports_delta_min=999,
            gate_monolith_hub_loc_delta_min=999,
            gate_monolith_crossarea_min_distinct_areas=999,
            gate_monolith_catchall_basenames=["utils.py"],
            gate_monolith_catchall_dirs=["utils"],
            gate_monolith_catchall_allowlist=[],
        )
        assert ok is True
        assert "MONOLITH: PASS" in _read_log(tmp_path)
    finally:
        logger.close()
