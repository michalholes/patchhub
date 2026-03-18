import subprocess
import sys
from pathlib import Path


def test_am_patch_runs_and_prints_version():
    """
    Smoke test: over\u00ed, \u017ee runner sa d\u00e1 spusti\u0165 a vyp\u00ed\u0161e verziu.
    Neoveruje konkr\u00e9tne \u010d\u00edslo verzie, iba \u017ee v\u00fdstup nie je pr\u00e1zdny
    a n\u00e1vratov\u00fd k\u00f3d je 0.
    """
    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "scripts" / "am_patch.py"

    assert runner.exists(), "scripts/am_patch.py not found"

    proc = subprocess.run(
        [sys.executable, str(runner), "--version"],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"runner exited with {proc.returncode}, stderr={proc.stderr!r}"
    assert proc.stdout.strip(), "runner --version produced empty output"
