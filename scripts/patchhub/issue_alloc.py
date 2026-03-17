from __future__ import annotations

import re
from pathlib import Path


def find_existing_issue_ids(patches_root: Path, default_regex: str) -> set[int]:
    rx = re.compile(default_regex)
    ids: set[int] = set()

    # Look in logs and artifacts directories for issue markers.
    for rel in ["logs", "artifacts", "successful", "unsuccessful"]:
        p = patches_root / rel
        if not p.exists():
            continue
        for item in p.rglob("*"):
            m = rx.search(str(item))
            if not m:
                continue
            try:
                ids.add(int(m.group(1)))
            except (ValueError, IndexError):
                continue

    return ids


def allocate_next_issue_id(
    patches_root: Path,
    default_regex: str,
    allocation_start: int,
    allocation_max: int,
) -> int:
    existing = find_existing_issue_ids(patches_root, default_regex)
    cur = max(existing) + 1 if existing else allocation_start
    if cur < allocation_start:
        cur = allocation_start
    if cur > allocation_max:
        raise ValueError("Issue allocation exceeded allocation_max")
    return cur
