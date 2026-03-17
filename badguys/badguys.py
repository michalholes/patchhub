#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    # Allow running from repo root with: python3 badguys/badguys.py ...
    # Ensure repo root (parent of badguys/) is on sys.path.
    repo_root = Path(__file__).resolve().parents[1]
    s = str(repo_root)
    if sys.path and sys.path[0] == s:
        pass
    elif s in sys.path:
        sys.path.remove(s)
        sys.path.insert(0, s)
    else:
        sys.path.insert(0, s)

    from badguys.run_suite import main as suite_main

    return int(suite_main(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
