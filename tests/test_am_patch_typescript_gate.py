from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _import_gate_module():
    import am_patch.gate_typescript as mod

    return mod


def _import_run_gates():
    from am_patch.errors import RunnerError
    from am_patch.gates import run_gates

    return run_gates, RunnerError


def _run_gates_kwargs(*, decision_paths: list[str]) -> dict[str, object]:
    return {
        "run_all": False,
        "compile_check": False,
        "compile_targets": ["."],
        "compile_exclude": [],
        "allow_fail": False,
        "skip_dont_touch": True,
        "dont_touch_paths": [],
        "skip_ruff": True,
        "skip_js": True,
        "skip_biome": True,
        "skip_typescript": False,
        "skip_pytest": True,
        "skip_mypy": True,
        "skip_docs": True,
        "skip_monolith": True,
        "skip_badguys": True,
        "gate_monolith_enabled": False,
        "gate_monolith_mode": "strict",
        "gate_monolith_scan_scope": "patch",
        "gate_monolith_extensions": [],
        "gate_monolith_compute_fanin": False,
        "gate_monolith_on_parse_error": "fail",
        "gate_monolith_areas_prefixes": [],
        "gate_monolith_areas_names": [],
        "gate_monolith_areas_dynamic": [],
        "gate_monolith_large_loc": 900,
        "gate_monolith_huge_loc": 1300,
        "gate_monolith_large_allow_loc_increase": 20,
        "gate_monolith_huge_allow_loc_increase": 0,
        "gate_monolith_large_allow_exports_delta": 2,
        "gate_monolith_huge_allow_exports_delta": 0,
        "gate_monolith_large_allow_imports_delta": 1,
        "gate_monolith_huge_allow_imports_delta": 0,
        "gate_monolith_new_file_max_loc": 400,
        "gate_monolith_new_file_max_exports": 25,
        "gate_monolith_new_file_max_imports": 15,
        "gate_monolith_hub_fanin_delta": 5,
        "gate_monolith_hub_fanout_delta": 5,
        "gate_monolith_hub_exports_delta_min": 3,
        "gate_monolith_hub_loc_delta_min": 100,
        "gate_monolith_crossarea_min_distinct_areas": 3,
        "gate_monolith_catchall_basenames": [],
        "gate_monolith_catchall_dirs": [],
        "gate_monolith_catchall_allowlist": [],
        "docs_include": [],
        "docs_exclude": [],
        "docs_required_files": [],
        "docs_status_entries": [],
        "js_extensions": [".js"],
        "js_command": ["node", "--check"],
        "biome_extensions": [],
        "biome_command": [],
        "biome_format": False,
        "biome_format_command": [],
        "biome_autofix": False,
        "biome_fix_command": [],
        "typescript_extensions": [".js", ".ts", ".tsx", ".mts", ".cts", ".d.ts"],
        "typescript_command": ["npx", "--yes", "tsc", "--noEmit", "--pretty", "false"],
        "gate_typescript_mode": "auto",
        "typescript_targets": ["scripts/patchhub/static/", "types/"],
        "gate_typescript_base_tsconfig": "tsconfig.json",
        "ruff_format": False,
        "ruff_autofix": False,
        "ruff_targets": [],
        "pytest_targets": [],
        "mypy_targets": [],
        "gate_ruff_mode": "always",
        "gate_mypy_mode": "always",
        "gate_pytest_mode": "always",
        "gate_pytest_py_prefixes": [],
        "gate_pytest_js_prefixes": [],
        "gate_badguys_mode": "auto",
        "gate_badguys_trigger_prefixes": [],
        "gate_badguys_trigger_files": [],
        "gate_badguys_command": [],
        "badguys_changed_entries": [],
        "pytest_routing_policy": {"pytest_routing_mode": "legacy"},
        "gates_order": ["typescript"],
        "pytest_use_venv": False,
        "decision_paths": decision_paths,
        "progress": None,
        "gate_step_callback": None,
    }


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.commands: list[list[str]] = []

    def warning_core(self, msg: str) -> None:
        self.warnings.append(msg)

    def error_core(self, _msg: str) -> None:
        return None

    def section(self, _msg: str) -> None:
        return None

    def line(self, _msg: str) -> None:
        return None

    def run_logged(self, argv: list[str], *, cwd: Path, env=None):
        import subprocess

        self.commands.append(list(argv))
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
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


def test_collect_changed_typescript_root_candidates_filters_targets() -> None:
    mod = _import_gate_module()
    candidates = mod.collect_changed_typescript_root_candidates(
        [
            "scripts/patchhub/static/a.js",
            "scripts/patchhub/static/z.js",
            "types/ok.d.ts",
            "types/ignored.txt",
            "other/a.js",
        ],
        targets=["scripts/patchhub/static/", "types/"],
        extensions=[".js", ".d.ts"],
    )
    assert candidates == [
        "scripts/patchhub/static/a.js",
        "scripts/patchhub/static/z.js",
        "types/ok.d.ts",
    ]


def test_write_typescript_gate_tsconfig_uses_files_for_root_scope(tmp_path: Path) -> None:
    mod = _import_gate_module()
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    gen_path = mod.write_typescript_gate_tsconfig(
        tmp_path,
        base_tsconfig="tsconfig.json",
        root_files=["types/root.d.ts"],
    )
    payload = json.loads(gen_path.read_text(encoding="utf-8"))
    assert payload == {
        "extends": "../tsconfig.json",
        "files": ["../types/root.d.ts"],
        "include": [],
    }


def test_run_gates_typescript_uses_changed_root_files_only(tmp_path: Path) -> None:
    run_gates, _ = _import_run_gates()
    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {"allowJs": True, "checkJs": True, "noEmit": True},
                "include": ["scripts/patchhub/static/**/*.js", "types/**/*.d.ts"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    target_dir = tmp_path / "scripts" / "patchhub" / "static"
    target_dir.mkdir(parents=True)
    (target_dir / "a.js").write_text("export const value = 1;\n", encoding="utf-8")
    (target_dir / "b.js").write_text("export const untouched = 2;\n", encoding="utf-8")

    logger = _Logger()
    run_gates(
        logger,  # type: ignore[arg-type]
        cwd=tmp_path,
        repo_root=tmp_path,
        **_run_gates_kwargs(decision_paths=["scripts/patchhub/static/a.js"]),
    )

    payload = json.loads(
        (tmp_path / ".am_patch" / "tsconfig.typescript_gate.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "extends": "../tsconfig.json",
        "files": ["../scripts/patchhub/static/a.js"],
        "include": [],
    }
    assert "gate_typescript=SKIP (no_matching_files)" not in logger.warnings
    assert "gate_typescript=SKIP (no_existing_root_files)" not in logger.warnings
    assert len(logger.commands) == 1


def test_run_gates_typescript_base_tsconfig_change_uses_full_scope(tmp_path: Path) -> None:
    run_gates, _ = _import_run_gates()
    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {"allowJs": True, "checkJs": True, "noEmit": True},
                "include": ["scripts/patchhub/static/**/*.js", "types/**/*.d.ts"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "patchhub" / "static").mkdir(parents=True)
    (tmp_path / "types").mkdir(parents=True)
    (tmp_path / "scripts" / "patchhub" / "static" / "a.js").write_text(
        "export const value = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / "types" / "ok.d.ts").write_text(
        "export type Ok = string;\n",
        encoding="utf-8",
    )

    logger = _Logger()
    run_gates(
        logger,  # type: ignore[arg-type]
        cwd=tmp_path,
        repo_root=tmp_path,
        **_run_gates_kwargs(decision_paths=["tsconfig.json"]),
    )

    payload = json.loads(
        (tmp_path / ".am_patch" / "tsconfig.typescript_gate.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "extends": "../tsconfig.json",
        "include": [
            "../scripts/patchhub/static/**/*",
            "../types/**/*",
        ],
    }
    assert "gate_typescript=SKIP (no_matching_files)" not in logger.warnings
    assert "gate_typescript=SKIP (no_existing_root_files)" not in logger.warnings
    assert len(logger.commands) == 1


def test_run_gates_typescript_skips_when_only_deleted_root_changed(tmp_path: Path) -> None:
    run_gates, _ = _import_run_gates()
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    logger = _Logger()
    run_gates(
        logger,  # type: ignore[arg-type]
        cwd=tmp_path,
        repo_root=tmp_path,
        **_run_gates_kwargs(decision_paths=["types/deleted.d.ts"]),
    )
    assert "gate_typescript=SKIP (no_existing_root_files)" in logger.warnings
    assert logger.commands == []


def test_run_gates_typescript_follows_imported_dependency_errors(tmp_path: Path) -> None:
    run_gates, runner_error = _import_run_gates()
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"noEmit": True}}) + "\n",
        encoding="utf-8",
    )
    types_dir = tmp_path / "types"
    types_dir.mkdir(parents=True)
    (types_dir / "root.ts").write_text(
        'import { value } from "./dep";\nexport const root = value;\n',
        encoding="utf-8",
    )
    (types_dir / "dep.ts").write_text(
        "const value: MissingName = 1;\nexport { value };\n",
        encoding="utf-8",
    )

    logger = _Logger()
    with pytest.raises(runner_error) as excinfo:
        run_gates(
            logger,  # type: ignore[arg-type]
            cwd=tmp_path,
            repo_root=tmp_path,
            **_run_gates_kwargs(decision_paths=["types/root.ts"]),
        )
    assert "gate failed: typescript" in str(excinfo.value)
    payload = json.loads(
        (tmp_path / ".am_patch" / "tsconfig.typescript_gate.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "extends": "../tsconfig.json",
        "files": ["../types/root.ts"],
        "include": [],
    }
