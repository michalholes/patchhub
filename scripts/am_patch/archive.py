from __future__ import annotations

import contextlib
import os
import shutil
import zipfile
from pathlib import Path

from .log import Logger


def _target_repo_name_payload(target_repo_name: str) -> bytes:
    text = str(target_repo_name).strip()
    if not text:
        raise ValueError("target_repo_name must be non-empty")
    if "\n" in text or "\r" in text:
        raise ValueError("target_repo_name must be a single line")
    if any(ch.isspace() for ch in text):
        raise ValueError("target_repo_name must not contain whitespace")
    if "/" in text or "\\" in text:
        raise ValueError("target_repo_name must be a bare token (no path separators)")
    try:
        payload = text.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError("target_repo_name must be ASCII-only") from e
    return payload + b"\n"


def _tmp_path_for_atomic_write(target: Path) -> Path:
    # Deterministic within process, avoids time/random.
    return target.with_name(f".{target.name}.tmp.{os.getpid()}")


def _fsync_file(path: Path) -> None:
    with open(path, "rb") as f:
        os.fsync(f.fileno())


def _fsync_dir(path: Path) -> None:
    # Best-effort on platforms without O_DIRECTORY.
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def pick_versioned_dest(dest: Path) -> Path:
    """Return a non-existing path by adding _vN suffix when needed.

    Contract:
    - If dest does not exist, return dest.
    - If it exists, return dest with suffix _v2, _v3, ... (first available).
    """
    if not dest.exists():
        return dest

    stem = dest.stem
    suf = dest.suffix
    i = 2
    while True:
        cand = dest.with_name(f"{stem}_v{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _should_move_to_archive(*, patch_script: Path, dest_dir: Path) -> bool:
    """Move only for non-archived inputs under canonical patches/.

    Keep copy semantics for reruns from patches/successful/ or
    patches/unsuccessful/ so archived inputs remain in place.
    """
    try:
        resolved_patch = patch_script.resolve()
        resolved_dest = dest_dir.resolve()
    except Exception:
        resolved_patch = patch_script
        resolved_dest = dest_dir

    patches_dir = resolved_dest.parent
    successful_dir = patches_dir / "successful"
    unsuccessful_dir = patches_dir / "unsuccessful"

    if not _is_within(patches_dir, resolved_patch):
        return False
    if _is_within(successful_dir, resolved_patch):
        return False
    return not _is_within(unsuccessful_dir, resolved_patch)


def archive_patch(logger: Logger, patch_script: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / patch_script.name

    # If exists, add suffix
    dest = pick_versioned_dest(dest)

    if _should_move_to_archive(patch_script=patch_script, dest_dir=dest_dir):
        shutil.move(str(patch_script), str(dest))
        action = "moved"
    else:
        shutil.copy2(patch_script, dest)
        action = "copied"

    logger.section("ARCHIVE PATCH")
    logger.line(f"archived patch script ({action}) to: {dest}")
    logger.info_core(f"archive_patch={dest}")
    return dest


def make_failure_zip(
    logger: Logger,
    zip_path: Path,
    *,
    workspace_repo: Path,
    log_path: Path,
    include_repo_files: list[str],
    include_patch_blobs: list[tuple[str, bytes]] | None = None,
    include_patch_paths: list[Path] | None = None,
    target_repo_name: str = "audiomason2",
    log_dir_name: str = "logs",
    patch_dir_name: str = "patches",
) -> None:
    """Create patched.zip for failure/diagnostics.

    Contract:
    - Always includes the primary log under <log_dir_name>/<name>.
    - Includes only a subset of repo files from the workspace (changed/touched union).
    - Includes patch inputs only when requested (e.g. patch not applied, or
      individual failed .patch files).
    """
    logger.section("FAILURE ZIP")
    logger.info_core(f"failure_zip=CREATE path={zip_path}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    # De-dup, keep deterministic order.
    seen: set[str] = set()
    files: list[str] = []
    for rel_str in include_repo_files:
        rp = rel_str.strip().lstrip("/")
        if not rp or rp in seen:
            continue
        seen.add(rp)
        files.append(rp)
    files.sort()

    patch_blobs = include_patch_blobs or []
    patch_paths = include_patch_paths or []

    # De-dup patch entries by archive name.
    seen_patch: set[str] = set()

    tmp_path = _tmp_path_for_atomic_write(zip_path)
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()

    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("target.txt", _target_repo_name_payload(target_repo_name))
            if log_path.exists():
                z.write(log_path, arcname=f"{log_dir_name}/{log_path.name}")

            for name, data in patch_blobs:
                arc = f"{patch_dir_name}/{Path(name).name}"
                if arc in seen_patch:
                    continue
                seen_patch.add(arc)
                z.writestr(arc, data)

            for patch_path in patch_paths:
                if not patch_path.exists():
                    continue
                arcname: str = f"{patch_dir_name}/{patch_path.name}"
                if arcname in seen_patch:
                    continue
                seen_patch.add(arcname)
                z.write(patch_path, arcname=arcname)

            for rel in files:
                src = (workspace_repo / rel).resolve()
                try:
                    src.relative_to(workspace_repo.resolve())
                except Exception:
                    continue
                if src.is_file():
                    z.write(src, arcname=rel)

        _fsync_file(tmp_path)
        os.replace(tmp_path, zip_path)
        _fsync_dir(zip_path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()

    logger.line(f"created failure zip: {zip_path}")
    logger.info_core(f"failure_zip=OK path={zip_path}")
