from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


def _run(argv: list[str], *, cwd: Path) -> str:
    p = subprocess.run(
        argv,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return p.stdout.strip()


def test_issue_diff_bundle_includes_full_file_snapshots(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)

    _run(["git", "init"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)

    a_path = repo_dir / "a.txt"
    b_path = repo_dir / "b.bin"

    a_path.write_text("base\n", encoding="utf-8")
    b_path.write_bytes(b"\x00\x01\x02\x03")

    _run(["git", "add", "a.txt", "b.bin"], cwd=repo_dir)
    _run(["git", "commit", "-m", "base"], cwd=repo_dir)
    base_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo_dir)

    a_path.write_text("changed\n", encoding="utf-8")
    b_path.write_bytes(b"\x00\x01\x02\x03\x04\x05")

    _run(["git", "add", "a.txt", "b.bin"], cwd=repo_dir)
    _run(["git", "commit", "-m", "change"], cwd=repo_dir)

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch.issue_diff import make_issue_diff_zip  # noqa: PLC0415
    from am_patch.log import Logger  # noqa: PLC0415

    artifacts_dir = tmp_path / "artifacts"
    logs_dir = tmp_path / "logs"
    log_path = logs_dir / "test.log"
    symlink_path = logs_dir / "latest.log"

    logger = Logger(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level="quiet",
        log_level="quiet",
        symlink_enabled=False,
    )
    try:
        zip_path = make_issue_diff_zip(
            logger=logger,
            repo_root=repo_dir,
            artifacts_dir=artifacts_dir,
            logs_dir=logs_dir,
            base_sha=base_sha,
            issue_id="999",
            files_to_promote=["a.txt", "b.bin"],
            log_paths=[],
        )
    finally:
        logger.close()

    assert zip_path.exists()

    a_bytes = a_path.read_bytes()
    b_bytes = b_path.read_bytes()

    with zipfile.ZipFile(zip_path, "r") as z:
        assert "diff/a.txt.patch" in z.namelist()
        assert len(z.read("diff/a.txt.patch")) > 0

        assert z.read("files/a.txt") == a_bytes
        assert z.read("files/b.bin") == b_bytes

        manifest = z.read("manifest.txt").decode("utf-8")
        assert "snapshot_entries=2" in manifest
        assert f"SNAP files/a.txt bytes={len(a_bytes)}" in manifest
        assert f"SNAP files/b.bin bytes={len(b_bytes)}" in manifest
