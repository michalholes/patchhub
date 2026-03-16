from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


def _import_am_patch():
    scripts_dir = Path(__file__).parent.parent / "amp"
    sys.path.insert(0, str(scripts_dir))
    from am_patch.failure_zip import cleanup_for_issue, render_name
    from am_patch.workspace import bump_existing_workspace_attempt

    return bump_existing_workspace_attempt, cleanup_for_issue, render_name


@dataclass
class _PolicyStub:
    failure_zip_keep_per_issue: int = 1
    failure_zip_cleanup_glob_template: str = ""
    failure_zip_template: str = "patched_issue{issue}_v{attempt:02d}.zip"
    log_template_issue: str = "i_{issue}_{ts}.log"
    log_template_finalize: str = "f_{ts}.log"
    failure_zip_name: str = "patched.zip"


def test_finalize_attempt_bump_updates_meta(tmp_path: Path) -> None:
    bump_attempt, _, _ = _import_am_patch()

    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({"attempt": 3}), encoding="utf-8")

    new_attempt = bump_attempt(meta_path)
    assert new_attempt == 4
    obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert int(obj.get("attempt")) == 4


def test_retention_after_write_keep_one(tmp_path: Path) -> None:
    _, cleanup_for_issue, _ = _import_am_patch()
    policy = _PolicyStub(failure_zip_keep_per_issue=1)
    patch_dir = tmp_path

    (patch_dir / "patched_issue254_v03.zip").write_bytes(b"x")
    (patch_dir / "patched_issue254_v04.zip").write_bytes(b"x")

    cleanup_for_issue(patch_dir=patch_dir, policy=policy, issue="254")

    assert not (patch_dir / "patched_issue254_v03.zip").exists()
    assert (patch_dir / "patched_issue254_v04.zip").exists()


def test_render_uses_propagated_attempt(tmp_path: Path) -> None:
    _, _, render_name = _import_am_patch()
    policy = _PolicyStub(failure_zip_template="patched_issue{issue}_v{attempt:02d}.zip")

    log_path = tmp_path / "i_254_20200101.log"
    log_path.write_text("x", encoding="utf-8")

    name = render_name(policy=policy, issue="254", log_path=log_path, attempt=4)
    assert name.endswith("_v04.zip")
