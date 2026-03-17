from pathlib import Path

from badguys.bdg_loader import BdgAsset, BdgAssetEntry, BdgTest
from badguys.bdg_materializer import materialize_assets
from badguys.bdg_subst import SubstCtx


def _write_config(repo_root: Path) -> Path:
    cfg_dir = repo_root / "badguys"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.toml"
    path.write_text(
        """
[suite]
issue_id = "666"
runner_cmd = ["python3", "scripts/am_patch.py"]
runner_verbosity = "quiet"
console_verbosity = "quiet"
log_verbosity = "quiet"
patches_dir = "patches"
logs_dir = "patches/badguys_logs"
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
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def test_python_patch_script_materializes_to_valid_python(tmp_path: Path) -> None:
    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    bdg = BdgTest(
        test_id="test_py",
        makes_commit=False,
        is_guard=False,
        subjects={"declared": "docs/declared.txt"},
        assets={
            "patch": BdgAsset(
                asset_id="patch",
                kind="python_patch_script",
                content='ctx.write_text("declared", "declared\n")\n',
                entries=[],
                declared_subjects=["declared"],
            )
        },
        steps=[],
    )
    subst = SubstCtx(issue_id="666", now_stamp="20260307_150000")
    mats = materialize_assets(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        subst=subst,
        bdg=bdg,
    )

    source = mats.files["patch"].read_text(encoding="utf-8")
    compile(source, str(mats.files["patch"]), "exec")


def test_zip_python_entry_materializes_to_valid_python(tmp_path: Path) -> None:
    import zipfile

    repo_root = tmp_path
    cfg_path = _write_config(repo_root)
    bdg = BdgTest(
        test_id="test_py",
        makes_commit=False,
        is_guard=False,
        subjects={"declared": "docs/declared.txt"},
        assets={
            "bundle": BdgAsset(
                asset_id="bundle",
                kind="patch_zip_manifest",
                content=None,
                entries=[
                    BdgAssetEntry(
                        name="script_entry",
                        kind="python_patch_script",
                        zip_name="evil.py",
                        declared_subjects=["declared"],
                        content='ctx.write_text("declared", "zip\n")\n',
                    )
                ],
            )
        },
        steps=[],
    )
    subst = SubstCtx(issue_id="666", now_stamp="20260307_150000")
    mats = materialize_assets(
        repo_root=repo_root,
        config_path=cfg_path.relative_to(repo_root),
        subst=subst,
        bdg=bdg,
    )

    with zipfile.ZipFile(mats.files["bundle"]) as zf:
        source = zf.read("evil.py").decode("utf-8")
    compile(source, "evil.py", "exec")
