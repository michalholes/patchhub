from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from am_patch.pytest_bucket_routing import select_pytest_targets  # noqa: E402
from am_patch.pytest_namespace_config import (  # noqa: E402
    PYTEST_DEPENDENCIES_DEFAULT,
    PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    PYTEST_FULL_SUITE_PREFIXES_DEFAULT,
    PYTEST_NAMESPACE_MODULES_DEFAULT,
    PYTEST_ROOTS_DEFAULT,
    PYTEST_TREE_DEFAULT,
)
from am_patch.pytest_namespace_discovery import discover_namespace_ownership  # noqa: E402
from am_patch.pytest_namespace_routing import select_namespace_pytest_targets  # noqa: E402

TEST_TARGETS = ["tests"]


def _write(rel_path: str, text: str, *, root: Path) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    _write(
        "tests/test_amp_root.py",
        "from scripts.am_patch.cli import main\n",
        root=tmp_path,
    )
    _write(
        "tests/test_patchhub_ui.py",
        "from scripts.patchhub.app import create_app\n",
        root=tmp_path,
    )
    _write(
        "tests/test_badguys_runner.py",
        "from badguys.bdg_executor import execute_bdg_step\n",
        root=tmp_path,
    )
    _write(
        "tests/test_core_runtime.py",
        "from audiomason.core.runtime import run_job\n",
        root=tmp_path,
    )
    _write(
        "tests/test_file_io_service.py",
        "from plugins.file_io.service import FileService\n",
        root=tmp_path,
    )
    _write(
        "tests/test_import_flow.py",
        "from plugins.import.phase2_job_runner import run_job\n",
        root=tmp_path,
    )
    _write(
        "tests/test_web_interface_api.py",
        "from plugins.web_interface.core import WebInterfacePlugin\n",
        root=tmp_path,
    )
    _write(
        "tests/test_diag_cli.py",
        "from plugins.diagnostics_console.plugin import DiagnosticsConsolePlugin\n",
        root=tmp_path,
    )
    _write(
        "tests/test_syslog_plugin.py",
        "from plugins.syslog.plugin import SyslogPlugin\n",
        root=tmp_path,
    )
    _write(
        "tests/test_tui_shell.py",
        "from plugins.tui.plugin import TuiPlugin\n",
        root=tmp_path,
    )
    _write(
        "tests/test_cover_handler_flow.py",
        "from plugins.cover_handler.plugin import CoverHandlerPlugin\n",
        root=tmp_path,
    )
    _write(
        "tests/test_catchall_misc.py",
        "def test_misc() -> None:\n    assert True\n",
        root=tmp_path,
    )
    return tmp_path


def _bucketed_targets(
    *,
    decision_paths: list[str],
    repo_root: Path,
    pytest_roots=PYTEST_ROOTS_DEFAULT,
    pytest_tree=PYTEST_TREE_DEFAULT,
    pytest_namespace_modules=PYTEST_NAMESPACE_MODULES_DEFAULT,
    pytest_dependencies=PYTEST_DEPENDENCIES_DEFAULT,
    pytest_external_dependencies=PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
    pytest_full_suite_prefixes=PYTEST_FULL_SUITE_PREFIXES_DEFAULT,
) -> list[str]:
    discover_namespace_ownership.cache_clear()
    return select_namespace_pytest_targets(
        decision_paths=decision_paths,
        pytest_targets=TEST_TARGETS,
        pytest_roots=pytest_roots,
        pytest_tree=pytest_tree,
        pytest_namespace_modules=pytest_namespace_modules,
        pytest_dependencies=pytest_dependencies,
        pytest_external_dependencies=pytest_external_dependencies,
        pytest_full_suite_prefixes=pytest_full_suite_prefixes,
        repo_root=repo_root,
    )


def test_legacy_mode_returns_pytest_targets_only() -> None:
    targets = select_pytest_targets(
        decision_paths=["plugins/file_io/service.py"],
        pytest_targets=["tests/custom_a.py", "tests/custom_b.py"],
        routing_policy={"pytest_routing_mode": "legacy"},
    )
    assert targets == ["tests/custom_a.py", "tests/custom_b.py"]


def test_bucketed_wrapper_forwards_explicit_repo_root(tmp_path: Path) -> None:
    repo_root = tmp_path
    expected = ["tests/sentinel.py"]
    captured: dict[str, object] = {}

    def _spy(**kwargs: object) -> list[str]:
        captured["repo_root"] = kwargs["repo_root"]
        return expected

    with patch(
        "am_patch.pytest_bucket_routing.select_namespace_pytest_targets",
        side_effect=_spy,
    ) as spy:
        actual = select_pytest_targets(
            decision_paths=["plugins/file_io/service.py"],
            pytest_targets=TEST_TARGETS,
            routing_policy={"pytest_routing_mode": "bucketed"},
            repo_root=repo_root,
        )

    assert actual == expected
    assert captured["repo_root"] is repo_root
    spy.assert_called_once()


def test_bucketed_mode_always_includes_direct_changed_tests(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["tests/test_changed_case.py"],
        repo_root=repo_root,
    )
    assert "tests/test_changed_case.py" in targets
    assert "tests" not in targets


def test_amp_root_pulls_patchhub_and_badguys_via_reverse_dependencies(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["scripts/am_patch/runtime.py"],
        repo_root=repo_root,
    )
    assert "tests/test_amp_root.py" in targets
    assert "tests/test_patchhub_ui.py" in targets
    assert "tests/test_badguys_runner.py" in targets


def test_patchhub_change_does_not_pull_amp_root_suite(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["scripts/patchhub/app.py"],
        repo_root=repo_root,
    )
    assert "tests/test_patchhub_ui.py" in targets
    assert "tests/test_amp_root.py" not in targets


def test_cover_handler_change_pulls_import_suite(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["plugins/cover_handler/plugin.py"],
        repo_root=repo_root,
    )
    assert "tests/test_cover_handler_flow.py" in targets
    assert "tests/test_import_flow.py" in targets


def test_import_change_does_not_pull_provider_suites_solely_by_dependency(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["plugins/import/phase2_job_runner.py"],
        repo_root=repo_root,
    )
    assert "tests/test_import_flow.py" in targets
    assert "tests/test_file_io_service.py" not in targets
    assert "tests/test_cover_handler_flow.py" not in targets


def test_file_io_change_pulls_reverse_transitive_dependents(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["plugins/file_io/service.py"],
        repo_root=repo_root,
    )
    assert "tests/test_file_io_service.py" in targets
    assert "tests/test_import_flow.py" in targets
    assert "tests/test_web_interface_api.py" in targets
    assert "tests/test_diag_cli.py" in targets
    assert "tests/test_syslog_plugin.py" in targets
    assert "tests/test_tui_shell.py" in targets


def test_core_change_routes_to_root_suite_without_full_suite_escalation(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["src/audiomason/core/runtime.py"],
        repo_root=repo_root,
    )
    assert "tests/test_core_runtime.py" in targets
    assert "tests" not in targets


def test_unmatched_change_routes_to_catch_all_namespace_without_full_suite(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["tools/local_script.py"],
        repo_root=repo_root,
    )
    assert targets == ["tests/test_catchall_misc.py"]


def test_full_suite_prefix_is_the_only_global_escalation_surface(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["pyproject.toml"],
        repo_root=repo_root,
    )
    assert targets == ["tests"]


def test_external_dependency_layer_routes_without_collapsing_into_repo_edges(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    targets = _bucketed_targets(
        decision_paths=["plugins/text_utils/plugin.py"],
        repo_root=repo_root,
    )
    assert "tests/test_import_flow.py" in targets
    assert "tests/test_text_utils.py" not in targets


def test_synthetic_root_and_leafs_work_without_python_hardcode(tmp_path: Path) -> None:
    _write(
        "tests/test_hocico_1.py",
        "from hocico.hocico_1.api import run\n",
        root=tmp_path,
    )
    _write(
        "tests/test_hocico_2.py",
        "from hocico.hocico_2.api import run\n",
        root=tmp_path,
    )
    targets = _bucketed_targets(
        decision_paths=["src/hocico/hocico_1/api.py"],
        repo_root=tmp_path,
        pytest_roots={"hocico.*": "src/hocico/", "*": "*"},
        pytest_tree={
            "hocico.hocico_1": "src/hocico/hocico_1/",
            "hocico.hocico_2": "src/hocico/hocico_2/",
        },
        pytest_namespace_modules={
            "hocico": ["hocico"],
            "hocico.hocico_1": ["hocico.hocico_1"],
            "hocico.hocico_2": ["hocico.hocico_2"],
        },
        pytest_dependencies={},
        pytest_external_dependencies={},
        pytest_full_suite_prefixes=[],
    )
    assert targets == ["tests/test_hocico_1.py"]


def _actual_repo_ownership() -> dict[str, tuple[str, ...]]:
    discover_namespace_ownership.cache_clear()
    return dict(
        discover_namespace_ownership(
            str(REPO_ROOT),
            tuple(sorted(PYTEST_ROOTS_DEFAULT.items())),
            tuple(sorted(PYTEST_TREE_DEFAULT.items())),
            tuple(
                sorted(
                    (key, tuple(values)) for key, values in PYTEST_NAMESPACE_MODULES_DEFAULT.items()
                )
            ),
        )
    )


def _actual_repo_targets(*decision_paths: str) -> list[str]:
    discover_namespace_ownership.cache_clear()
    return select_namespace_pytest_targets(
        decision_paths=list(decision_paths),
        pytest_targets=TEST_TARGETS,
        pytest_roots=PYTEST_ROOTS_DEFAULT,
        pytest_tree=PYTEST_TREE_DEFAULT,
        pytest_namespace_modules=PYTEST_NAMESPACE_MODULES_DEFAULT,
        pytest_dependencies=PYTEST_DEPENDENCIES_DEFAULT,
        pytest_external_dependencies=PYTEST_EXTERNAL_DEPENDENCIES_DEFAULT,
        pytest_full_suite_prefixes=PYTEST_FULL_SUITE_PREFIXES_DEFAULT,
        repo_root=REPO_ROOT,
    )


def test_actual_repo_tooling_false_negatives_are_no_longer_catch_all() -> None:
    ownership = _actual_repo_ownership()

    amp_namespaces = ownership["tests/test_patch_jail_bwrap_preflight_issue904.py"]
    assert amp_namespaces != ("*",)
    assert "amp" in amp_namespaces

    for rel_path in (
        "tests/test_patchhub_zip_commit_message.py",
        "tests/test_patchhub_zip_issue_number.py",
    ):
        namespaces = ownership[rel_path]
        assert namespaces != ("*",)
        assert "amp.phb" in namespaces


def test_actual_repo_web_and_import_false_negatives_are_no_longer_catch_all() -> None:
    ownership = _actual_repo_ownership()

    expected_web_and_import = [
        "tests/e2e/test_import_ui_flow_editor_e2e.py",
        "tests/e2e/test_import_ui_run_wizard_e2e.py",
        "tests/e2e/test_web_interface_app_e2e.py",
        "tests/e2e/test_web_interface_smoke.py",
    ]
    for rel_path in expected_web_and_import:
        namespaces = ownership[rel_path]
        assert namespaces != ("*",)
        assert "am2.plugins.web_interface" in namespaces
        assert "am2.plugins.import" in namespaces

    for rel_path in (
        "tests/unit/test_web_interface_wizards_backward_compat.py",
        "tests/unit/test_web_interface_wizards_validation.py",
    ):
        namespaces = ownership[rel_path]
        assert namespaces != ("*",)
        assert "am2.plugins.web_interface" in namespaces


def test_import_change_pulls_web_and_import_e2e_surfaces_in_actual_repo() -> None:
    targets = _actual_repo_targets("plugins/import/plugin.py")
    assert "tests/e2e/test_import_ui_flow_editor_e2e.py" in targets
    assert "tests/e2e/test_import_ui_run_wizard_e2e.py" in targets
    assert "tests/e2e/test_web_interface_app_e2e.py" in targets
    assert "tests/e2e/test_web_interface_smoke.py" in targets


def test_web_interface_change_pulls_web_and_import_e2e_surfaces_in_actual_repo() -> None:
    targets = _actual_repo_targets("plugins/web_interface/core.py")
    assert "tests/e2e/test_import_ui_flow_editor_e2e.py" in targets
    assert "tests/e2e/test_import_ui_run_wizard_e2e.py" in targets
    assert "tests/e2e/test_web_interface_app_e2e.py" in targets
    assert "tests/e2e/test_web_interface_smoke.py" in targets


def test_file_io_change_keeps_consumer_and_web_surfaces_in_actual_repo() -> None:
    targets = _actual_repo_targets("plugins/file_io/plugin.py")
    assert "tests/unit/test_file_io_service.py" in targets
    assert "tests/e2e/test_import_ui_run_wizard_e2e.py" in targets
    assert "tests/e2e/test_web_interface_app_e2e.py" in targets


def test_actual_repo_unmatched_script_changes_route_via_catchall_path_evidence() -> None:
    check_patch_targets = _actual_repo_targets("scripts/check_patch_pm.py")
    assert "tests/test_check_patch_pm.py" in check_patch_targets
    assert "tests/test_scripts_cli_help.py" in check_patch_targets
    assert "tests" not in check_patch_targets

    gov_versions_targets = _actual_repo_targets("scripts/gov_versions.py")
    assert "tests/test_scripts_cli_help.py" in gov_versions_targets
    assert "tests" not in gov_versions_targets

    sync_targets = _actual_repo_targets("scripts/sync_issues_archive.py")
    assert "tests/test_scripts_cli_help.py" in sync_targets
    assert "tests" not in sync_targets


def test_unmatched_change_uses_helper_path_evidence_before_generic_catch_all(
    tmp_path: Path,
) -> None:
    repo_root = _make_repo(tmp_path)
    _write(
        "tests/tooling_support.py",
        """from pathlib import Path

def _tool_script() -> Path:
    return Path("tools") / "future_script.py"

def tool_script_path(repo_root: Path) -> Path:
    return repo_root / _tool_script()
""",
        root=repo_root,
    )
    _write(
        "tests/test_tooling_help.py",
        """import subprocess
import sys
from pathlib import Path

from tests.tooling_support import tool_script_path


def test_help_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, str(tool_script_path(repo_root)), "--help"],
        check=False,
    )
""",
        root=repo_root,
    )

    targets = _bucketed_targets(
        decision_paths=["tools/future_script.py"],
        repo_root=repo_root,
    )
    assert targets == ["tests/test_tooling_help.py"]


def test_patchhub_change_does_not_pull_import_only_e2e_from_asset_inventory_helper() -> None:
    targets = _actual_repo_targets("scripts/patchhub/app.py")
    assert "tests/e2e/test_patchhub_debug_ui_e2e.py" in targets
    assert "tests/e2e/test_import_ui_run_wizard_e2e.py" not in targets
    assert "tests/e2e/test_import_ui_flow_editor_e2e.py" not in targets
    assert "tests/e2e/test_web_interface_smoke.py" not in targets
