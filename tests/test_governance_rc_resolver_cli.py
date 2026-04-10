from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "governance" / "rc_resolver.py"
MODULE = [sys.executable, "-m", "governance.rc_resolver"]
DIRECT = [sys.executable, str(SCRIPT)]
SPEC_PATH = "governance/specification.jsonl"
TARGET = "governance/rc_resolver.py"


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_minimal_snapshot(path: Path) -> None:
    members = {
        "governance/rc_resolver.py": (REPO_ROOT / "governance" / "rc_resolver.py").read_bytes(),
        "governance/specification.jsonl": (
            REPO_ROOT / "governance" / "specification.jsonl"
        ).read_bytes(),
        "governance/governance.jsonl": (REPO_ROOT / "governance" / "governance.jsonl").read_bytes(),
    }
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _run_resolver(
    cmd: list[str],
    *,
    cwd: Path,
    snapshot: Path,
    handoff: Path,
    pack: Path,
    digest: Path,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            *cmd,
            TARGET,
            "--workspace-snapshot",
            str(snapshot),
            "--spec",
            SPEC_PATH,
            "--handoff-output",
            str(handoff),
            "--pack-output",
            str(pack),
            "--hash-output",
            str(digest),
        ],
        cwd=cwd,
    )


def test_rc_resolver_direct_script_help_from_outside_repo_cwd() -> None:
    proc = _run([*DIRECT, "--help"], cwd=Path("/tmp"))

    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout


def test_rc_resolver_direct_script_and_module_outputs_match(tmp_path: Path) -> None:
    snapshot = tmp_path / "patchhub-main_issue489.zip"
    _write_minimal_snapshot(snapshot)

    direct_handoff = tmp_path / "direct_HANDOFF.md"
    direct_pack = tmp_path / "direct_constraint_pack.json"
    direct_hash = tmp_path / "direct_hash_pack.txt"
    direct_proc = _run_resolver(
        DIRECT,
        cwd=REPO_ROOT,
        snapshot=snapshot,
        handoff=direct_handoff,
        pack=direct_pack,
        digest=direct_hash,
    )

    module_handoff = tmp_path / "module_HANDOFF.md"
    module_pack = tmp_path / "module_constraint_pack.json"
    module_hash = tmp_path / "module_hash_pack.txt"
    module_proc = _run_resolver(
        MODULE,
        cwd=REPO_ROOT,
        snapshot=snapshot,
        handoff=module_handoff,
        pack=module_pack,
        digest=module_hash,
    )

    assert direct_proc.returncode == 0, direct_proc.stderr
    assert module_proc.returncode == 0, module_proc.stderr
    assert direct_proc.stdout.strip() == "RESULT: PASS"
    assert module_proc.stdout.strip() == "RESULT: PASS"

    assert direct_pack.read_bytes() == module_pack.read_bytes()
    assert direct_hash.read_bytes() == module_hash.read_bytes()
    assert direct_handoff.read_text(encoding="utf-8") == module_handoff.read_text(encoding="utf-8")

    payload = direct_pack.read_bytes()
    assert direct_hash.read_text(encoding="utf-8") == hashlib.sha256(payload).hexdigest() + "\n"
    pack = json.loads(payload.decode("utf-8"))
    assert pack["target_scope"] == "implementation_scope"
    assert pack["mode"] == "final"
