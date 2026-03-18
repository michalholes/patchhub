from pathlib import Path

import pytest
from badguys.bdg_executor import execute_bdg_step
from badguys.bdg_loader import BdgAsset, BdgStep, BdgTest
from badguys.bdg_materializer import materialize_assets
from badguys.bdg_recipe import step_recipe
from badguys.bdg_subst import SubstCtx


def _write_alt_config(repo_root: Path, *, include_commit_limit_step: bool = True) -> Path:
    cfg_dir = repo_root / "badguys"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "alt.toml"
    text = """
[suite]
issue_id = "777"
runner_cmd = ["python3", "scripts/am_patch.py"]
runner_verbosity = "quiet"
console_verbosity = "quiet"
log_verbosity = "quiet"
patches_dir = "patches"
logs_dir = "patches/badguys_logs_alt"
commit_limit = 0

[lock]
path = "patches/badguys.lock"
ttl_seconds = 3600
on_conflict = "fail"

[guard]
require_guard_test = false
guard_test_name = "test_000_test_mode_smoke"
abort_on_guard_fail = true

[filters]
include = []
exclude = []

[runner]
full_runner_tests = []

[recipes.tests.test_cfg.steps.0]
runner_verbosity = "debug"
""".strip()
    if include_commit_limit_step:
        text += "\n\n[recipes.tests.test_cfg.steps.1]\ncommit_limit = 7"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _write_alt_config_with_legacy_subject(repo_root: Path) -> Path:
    path = _write_alt_config(repo_root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n[subjects.tests.test_cfg.subject_a]\n")
        fh.write('relpath = "docs/alt_subject.txt"\n')
    return path


def _step_runner_cfg(repo_root: Path) -> dict[str, object]:
    return {
        "artifacts_dir": repo_root / "patches" / "artifacts",
        "console_verbosity": "quiet",
        "copy_runner_log": False,
        "patches_dir": repo_root / "patches",
        "write_subprocess_stdio": False,
    }


def test_step_recipe_uses_selected_config_path(tmp_path: Path) -> None:
    repo_root = tmp_path
    alt_path = _write_alt_config(repo_root)

    recipe = step_recipe(
        repo_root=repo_root,
        config_path=alt_path.relative_to(repo_root),
        test_id="test_cfg",
        step_index=0,
    )

    assert recipe == {"runner_verbosity": "debug"}


def test_build_cfg_appends_recipe_commit_limit_override(tmp_path: Path) -> None:
    repo_root = tmp_path
    alt_path = _write_alt_config(repo_root, include_commit_limit_step=True)
    bdg = BdgTest(
        test_id="test_cfg",
        makes_commit=False,
        is_guard=False,
        assets={
            "cfg": BdgAsset(
                asset_id="cfg",
                kind="toml_text",
                content='[suite]\nrunner_verbosity = "quiet"\ncommit_limit = 0\n',
                entries=[],
            )
        },
        steps=[
            BdgStep(op="BUILD_CFG", params={"input_asset": "cfg"}),
            BdgStep(op="BUILD_CFG", params={"input_asset": "cfg"}),
        ],
    )
    subst = SubstCtx(issue_id="777", now_stamp="20260307_150000")
    mats = materialize_assets(
        repo_root=repo_root,
        config_path=alt_path.relative_to(repo_root),
        subst=subst,
        bdg=bdg,
    )

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=alt_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py", "--verbosity=quiet"],
        subst=subst,
        full_runner_tests=set(),
        step=bdg.steps[1],
        mats=mats,
        test_id=bdg.test_id,
        step_index=1,
        step_runner_cfg=_step_runner_cfg(repo_root),
    )

    assert result.rc == 0
    assert result.value is not None
    assert "--commit-limit=7" in result.value


def test_build_cfg_uses_recipe_from_selected_config_path(tmp_path: Path) -> None:
    repo_root = tmp_path
    alt_path = _write_alt_config(repo_root, include_commit_limit_step=False)
    bdg = BdgTest(
        test_id="test_cfg",
        makes_commit=False,
        is_guard=False,
        assets={
            "cfg": BdgAsset(
                asset_id="cfg",
                kind="toml_text",
                content='[suite]\nrunner_verbosity = "quiet"\n',
                entries=[],
            )
        },
        steps=[BdgStep(op="BUILD_CFG", params={"input_asset": "cfg"})],
    )
    subst = SubstCtx(issue_id="777", now_stamp="20260307_150000")
    mats = materialize_assets(
        repo_root=repo_root,
        config_path=alt_path.relative_to(repo_root),
        subst=subst,
        bdg=bdg,
    )

    result = execute_bdg_step(
        repo_root=repo_root,
        config_path=alt_path.relative_to(repo_root),
        cfg_runner_cmd=["python3", "scripts/am_patch.py", "--verbosity=quiet"],
        subst=subst,
        full_runner_tests=set(),
        step=bdg.steps[0],
        mats=mats,
        test_id=bdg.test_id,
        step_index=0,
        step_runner_cfg=_step_runner_cfg(repo_root),
    )

    assert result.rc == 0
    assert result.value is not None
    assert "--verbosity=debug" in result.value
    assert "--verbosity=quiet" not in result.value


def test_materialize_assets_rejects_legacy_subject_authority(tmp_path: Path) -> None:
    repo_root = tmp_path
    alt_path = _write_alt_config_with_legacy_subject(repo_root)
    bdg = BdgTest(
        test_id="test_cfg",
        makes_commit=False,
        is_guard=False,
        subjects={"subject_a": "docs/alt_subject.txt"},
        assets={},
        steps=[BdgStep(op="RUN_RUNNER", params={})],
    )

    with pytest.raises(SystemExit, match=r"per-test \[subjects\] moved to \.bdg"):
        materialize_assets(
            repo_root=repo_root,
            config_path=alt_path.relative_to(repo_root),
            subst=SubstCtx(issue_id="777", now_stamp="20260307_150000"),
            bdg=bdg,
        )
