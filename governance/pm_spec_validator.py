import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

PATCH_PREFIX = "patches/per_file/"
PATCH_SUFFIX = ".patch"
SUBOR_PREFIX = "Subor: `"


def fail(code: str, detail: str) -> None:
    print("RESULT: FAIL")
    print(f"RULE {code}: FAIL - {detail}")
    raise SystemExit(1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_id")
    parser.add_argument("commit_message")
    parser.add_argument("patch")
    parser.add_argument("--workspace-snapshot", required=True)
    parser.add_argument("--freeze", required=True)
    return parser.parse_args(argv)


def read_zip(path: Path) -> dict[str, bytes]:
    with ZipFile(path, "r") as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}


def patch_members(items: dict[str, bytes]) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    for name, raw in items.items():
        if not (name.startswith(PATCH_PREFIX) and name.endswith(PATCH_SUFFIX)):
            continue
        repo_path = name[len(PATCH_PREFIX) : -len(PATCH_SUFFIX)].replace("__", "/")
        members[repo_path] = raw
    if not members:
        fail("PATCH_LAYOUT", "no per-file patches found")
    return members


def parse_freeze(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    expected: dict[str, str] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not (line.startswith(SUBOR_PREFIX) and line.endswith("`")):
            idx += 1
            continue
        repo_path = line[len(SUBOR_PREFIX) : -1]
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines) or "REPLACE WHOLE FILE" not in lines[idx]:
            fail("FREEZE_PARSE", f"missing_replace_whole_file:{repo_path}")
        idx += 1
        while idx < len(lines) and not lines[idx].startswith("```"):
            idx += 1
        if idx >= len(lines):
            fail("FREEZE_PARSE", f"missing_code_block_start:{repo_path}")
        idx += 1
        body: list[str] = []
        while idx < len(lines) and not lines[idx].startswith("```"):
            body.append(lines[idx])
            idx += 1
        if idx >= len(lines):
            fail("FREEZE_PARSE", f"missing_code_block_end:{repo_path}")
        expected[repo_path] = "\n".join(body) + "\n"
        idx += 1
    if not expected:
        fail("FREEZE_PARSE", "no whole-file replacements found")
    return expected


def apply_patch(patch_zip: Path, workspace_snapshot: Path) -> tuple[Path, list[str]]:
    tempdir = Path(tempfile.mkdtemp(prefix="pm_spec_validator_"))
    subprocess.run(["unzip", "-q", str(workspace_snapshot), "-d", str(tempdir)], check=True)
    repo_root = tempdir
    items = read_zip(patch_zip)
    members = patch_members(items)
    patch_dir = tempdir / ".patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_files: list[str] = []
    for repo_path, raw in members.items():
        patch_path = patch_dir / (repo_path.replace("/", "__") + ".patch")
        patch_path.write_bytes(raw)
        patch_files.append(str(patch_path))
    check = subprocess.run(
        ["git", "apply", "--check", *sorted(patch_files)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        detail = check.stderr.strip() or check.stdout.strip() or "git apply --check failed"
        fail("APPLY_CHECK", detail)
    apply = subprocess.run(
        ["git", "apply", *sorted(patch_files)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if apply.returncode != 0:
        detail = apply.stderr.strip() or apply.stdout.strip() or "git apply failed"
        fail("APPLY", detail)
    return repo_root, sorted(members)


def exact_file_match(repo_root: Path, expected: dict[str, str]) -> None:
    for repo_path, text in expected.items():
        file_path = repo_root / repo_path
        if not file_path.is_file():
            fail("EXACT_FILE", f"missing={repo_path}")
        actual = file_path.read_text(encoding="utf-8")
        if actual != text:
            fail("EXACT_FILE", f"mismatch={repo_path}")


def forbid_second_truth(repo_root: Path) -> None:
    legacy = repo_root / "scripts/authority_resolver.py"
    if legacy.exists():
        fail("SECOND_TRUTH", "legacy scripts/authority_resolver.py still exists")
    text = (repo_root / "governance/rc_resolver.py").read_text(encoding="utf-8")
    if "scripts/authority_resolver.py" in text:
        fail("SECOND_TRUTH", "legacy reference remains in governance/rc_resolver.py")


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    expected = parse_freeze(Path(args.freeze))
    repo_root, changed = apply_patch(Path(args.patch), Path(args.workspace_snapshot))
    expected_paths = sorted(expected)
    if changed != expected_paths:
        fail("PATCH_SCOPE", f"expected={expected_paths}:actual={changed}")
    exact_file_match(repo_root, expected)
    forbid_second_truth(repo_root)
    print("RESULT: PASS")


if __name__ == "__main__":
    main(sys.argv[1:])
