from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch.errors import RunnerError
from am_patch.manifest import load_files
from am_patch.patch_archive_select import select_latest_issue_patch
from am_patch.patch_exec import precheck_patch_script
from am_patch.patch_select import PatchSelectError, choose_default_patch_input, decide_unified_mode
from am_patch.repo_root import is_under


@dataclass(frozen=True)
class PatchPlan:
    patch_script: Path
    unified_mode: bool
    files_declared: list[str]


def resolve_patch_plan(
    *,
    logger: Any,
    cli: Any,
    policy: Any,
    issue_id: int,
    repo_root: Path,
    patch_root: Path,
) -> PatchPlan:
    patch_script: Path | None = None

    if getattr(cli, "load_latest_patch", None):
        hint_name = Path(cli.patch_script).name if cli.patch_script else None
        patch_script = select_latest_issue_patch(
            patch_dir=patch_root,
            issue_id=str(issue_id),
            hint_name=hint_name,
        )
    elif cli.patch_script:
        raw = Path(cli.patch_script)
        if raw.is_absolute():
            patch_script = raw
        else:
            # Accept either:
            #  - a path relative to CWD (e.g. patches/issue_999.py), OR
            #  - a bare filename resolved under patch_dir (e.g. issue_999.py).
            cand_cwd = (Path.cwd() / raw).resolve()
            cand_patchdir = (patch_root / raw).resolve()
            if cand_cwd.exists() and is_under(cand_cwd, patch_root):
                patch_script = cand_cwd
            elif cand_patchdir.exists():
                patch_script = cand_patchdir
            else:
                raise RunnerError(
                    "PREFLIGHT",
                    "MANIFEST",
                    f"patch script not found (tried: {cand_cwd} and {cand_patchdir})",
                )
    else:
        try:
            patch_script = choose_default_patch_input(patch_root, issue_id)
        except PatchSelectError as e:
            raise RunnerError("PREFLIGHT", "MANIFEST", str(e)) from e

    assert patch_script is not None

    if not patch_script.exists():
        raise RunnerError("PREFLIGHT", "MANIFEST", f"patch script not found: {patch_script}")

    if not is_under(patch_script, patch_root):
        raise RunnerError(
            "PREFLIGHT",
            "PATCH_PATH",
            f"patch script must be under {patch_root} (got {patch_script})",
        )

    try:
        unified_mode = decide_unified_mode(
            patch_script,
            explicit_unified=bool(getattr(policy, "unified_patch", False)),
        )
    except PatchSelectError as e:
        raise RunnerError("PREFLIGHT", "PATCH_PATH", str(e)) from e

    if not unified_mode:
        precheck_patch_script(patch_script, ascii_only=policy.ascii_only_patch)

    files_declared: list[str] = [] if unified_mode else load_files(patch_script)

    return PatchPlan(
        patch_script=patch_script,
        unified_mode=unified_mode,
        files_declared=files_declared,
    )
