from __future__ import annotations

from pathlib import Path

from am_patch.errors import RunnerError


def select_latest_issue_patch(*, patch_dir: Path, issue_id: str, hint_name: str | None) -> Path:
    """Select the most recent patch script for ISSUE_ID from patches/, patches/successful/,
    patches/unsuccessful/.

    If hint_name is provided, it is treated as a filename hint (basename). The selection
    prefers that exact name and its archive variants (stem_vN.py). If no hint is provided,
    any script starting with "issue_<id>" is eligible.

    Selection order: newest mtime wins; ties broken by lexical path.
    """
    dirs = [patch_dir, patch_dir / "successful", patch_dir / "unsuccessful"]

    def iter_files(d: Path) -> list[Path]:
        """Return candidate archived patch inputs for -l.

        Supported inputs:
        - *.py   (patch script)
        - *.patch (unified diff)
        - *.zip  (bundle containing at least one *.patch entry)
        """
        import zipfile

        try:
            out: list[Path] = []
            for p in d.iterdir():
                if not p.is_file():
                    continue
                if p.suffix in (".py", ".patch"):
                    out.append(p)
                    continue
                if p.suffix == ".zip":
                    try:
                        with zipfile.ZipFile(p, "r") as z:
                            if any(n.endswith(".patch") for n in z.namelist()):
                                out.append(p)
                    except zipfile.BadZipFile:
                        # Ignore invalid zip files in archive dirs (deterministic: not candidates).
                        continue
            return out
        except FileNotFoundError:
            return []

    issue_prefix = f"issue_{issue_id}"
    hint_stem: str | None = None
    if hint_name:
        bn = Path(hint_name).name
        hint_stem = Path(bn).stem

    cands: list[Path] = []
    for d in dirs:
        for p in iter_files(d):
            name = p.name
            # If a hint_name was provided (explicit patch filename), select by basename
            # (and its _vN archive variants) regardless of ISSUE_ID prefix.
            if hint_stem is not None:
                if p.stem == hint_stem:
                    cands.append(p)
                    continue
                if p.stem.startswith(f"{hint_stem}_v"):
                    tail = p.stem[len(hint_stem) + 2 :]
                    if tail.isdigit():
                        cands.append(p)
                        continue
                continue

            # Otherwise (no hint), select by ISSUE_ID prefix.
            if not name.startswith(issue_prefix):
                continue
            cands.append(p)

    if not cands:
        raise RunnerError(
            "PREFLIGHT", "MANIFEST", f"-l: no archived patch scripts found for issue_id={issue_id}"
        )

    cands.sort(key=lambda p: (p.stat().st_mtime, str(p)), reverse=True)
    return cands[0]
