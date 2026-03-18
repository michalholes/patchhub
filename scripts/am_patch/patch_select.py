from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PatchSelectError(Exception):
    pass


@dataclass(frozen=True)
class PatchInputChoice:
    path: Path
    unified: bool


def _zip_contains_patch_entries(zip_path: Path) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            return any(n.endswith(".patch") for n in z.namelist())
    except zipfile.BadZipFile as e:
        raise PatchSelectError(f"invalid zip file: {zip_path} ({e})") from e


def choose_default_patch_input(patch_dir: Path, issue_id: int) -> Path:
    """Choose a default patch input for an issue when PATCH_PATH is omitted.

    Deterministic, fail-fast:
    - If exactly one of issue_{id}.patch / issue_{id}.zip / issue_{id}.py exists, use it.
    - If multiple exist, raise PatchSelectError (ambiguous).
    - If none exist, return issue_{id}.py (caller will error on missing, as before).
    """
    cands = [
        (patch_dir / f"issue_{issue_id}.patch").resolve(),
        (patch_dir / f"issue_{issue_id}.zip").resolve(),
        (patch_dir / f"issue_{issue_id}.py").resolve(),
    ]
    present = [p for p in cands if p.exists()]
    if len(present) == 1:
        return present[0]
    if len(present) > 1:
        names = ", ".join(str(p) for p in present)
        raise PatchSelectError(f"ambiguous default patch input; multiple exist: {names}")
    return cands[-1]


def decide_unified_mode(patch_input: Path, *, explicit_unified: bool) -> bool:
    """Decide whether to run in unified patch mode.

    Rules:
    - If explicit_unified is True, force unified patch mode and validate suffix.
    - Otherwise (auto):
      - .patch -> unified
      - .zip -> unified only if it contains at least one .patch entry; otherwise error
      - .py (and others) -> script mode
    """
    p = patch_input.resolve()
    if explicit_unified:
        if p.suffix not in (".patch", ".zip"):
            raise PatchSelectError(f"unified patch input must be .patch or .zip (got {p})")
        if p.suffix == ".zip" and not _zip_contains_patch_entries(p):
            raise PatchSelectError(f"zip contains no .patch entries: {p}")
        return True

    if p.suffix == ".patch":
        return True
    if p.suffix == ".zip":
        if not _zip_contains_patch_entries(p):
            raise PatchSelectError(
                f"cannot auto-detect zip input; zip contains no .patch entries: {p}"
            )
        return True
    return False
