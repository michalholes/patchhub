#!/usr/bin/env python3
"""
check_ascii.py

ASCII-only diagnostic scanner for source files.

Scans:
- *.py
- *.md

Skips:
- ./patches/** (by default)
- common tooling dirs (.git, .venv, venv, __pycache__, build, dist, etc.)
- the script file itself

Exit codes:
- 0: no non-ASCII found
- 1: non-ASCII found
- 2: invalid root / error

Usage:
  python3 scripts/check_ascii.py
  python3 scripts/check_ascii.py --root .
  python3 scripts/check_ascii.py --include patches
  python3 scripts/check_ascii.py --ext .py --ext .md
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "build",
    "dist",
    ".tox",
    ".eggs",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    col: int
    ch: str

    @property
    def codepoint(self) -> str:
        return f"U+{ord(self.ch):04X}"


def iter_files(
    root: Path, exts: Sequence[str], skip_patches: bool, self_path: Path
) -> Iterator[Path]:
    exts_lc = {e.lower() for e in exts}
    for p in root.rglob("*"):
        if not p.is_file():
            continue

        # Skip common directories
        if any(part in DEFAULT_SKIP_DIRS for part in p.parts):
            continue

        # Skip patches/ unless explicitly included
        if skip_patches and "patches" in p.parts:
            continue

        # Skip this script itself
        try:
            if p.resolve() == self_path:
                continue
        except OSError:
            # If resolve fails, fall back to string compare
            if str(p) == str(self_path):
                continue

        if p.suffix.lower() in exts_lc:
            yield p


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Treat undecodable as a hard finding: file is not valid UTF-8
        # Report at pseudo-position 1:1 with replacement char marker.
        findings.append(Finding(path=path, line=1, col=1, ch="�"))
        return findings

    for i, line in enumerate(data.splitlines(), start=1):
        for j, ch in enumerate(line, start=1):
            if ord(ch) >= 128:
                findings.append(Finding(path=path, line=i, col=j, ch=ch))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Repo root (default: .)")
    ap.add_argument(
        "--ext",
        action="append",
        default=[],
        help="File extension to scan (repeatable). Default: .py and .md",
    )
    ap.add_argument(
        "--include",
        action="append",
        default=[],
        help="Include normally-skipped areas. Example: --include patches",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"ERROR: invalid root: {root}", file=sys.stderr)
        return 2

    exts = args.ext if args.ext else [".py", ".md"]
    include = {x.strip().lower() for x in args.include}
    skip_patches = "patches" not in include

    self_path = Path(__file__).resolve()

    all_findings: list[Finding] = []
    files_scanned = 0

    for p in iter_files(root, exts=exts, skip_patches=skip_patches, self_path=self_path):
        files_scanned += 1
        all_findings.extend(scan_file(p))

    if not all_findings:
        print(f"OK: ASCII-only. Scanned {files_scanned} files ({', '.join(exts)}).")
        return 0

    # Report
    print(f"FAIL: found non-ASCII in {len(all_findings)} positions across {files_scanned} files.")
    for f in all_findings:
        rel = f.path.relative_to(root)
        safe = f.ch.encode("unicode_escape").decode("ascii")
        print(f"{rel}:{f.line}:{f.col}: {f.codepoint} '{safe}'")

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
