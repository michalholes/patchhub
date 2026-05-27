from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import cast

from .errors import RunnerError

_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<path>[^#\s]+)\s*$")


def _validate_paths(files: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for f in files:
        f = f.strip()
        if not f:
            continue
        if f.startswith("/") or f.startswith("~") or ".." in f.split("/"):
            raise RunnerError(
                "PREFLIGHT", "MANIFEST", f"invalid repo-relative path in FILES: {f!r}"
            )
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    if not out:
        raise RunnerError("PREFLIGHT", "MANIFEST", "FILES is empty")
    return out


def load_files(patch_script: Path) -> list[str]:
    text = patch_script.read_text(encoding="utf-8", errors="replace")

    # Primary: parse FILES = [...]
    try:
        tree = ast.parse(text, filename=str(patch_script))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "FILES":
                        value_obj = cast(object, ast.literal_eval(node.value))
                        if not isinstance(value_obj, list):
                            raise RunnerError("PREFLIGHT", "MANIFEST", "FILES must be a list")
                        parsed_files: list[str] = []
                        for item in cast(list[object], value_obj):
                            if not isinstance(item, str):
                                raise RunnerError(
                                    "PREFLIGHT",
                                    "MANIFEST",
                                    "FILES entries must be strings",
                                )
                            parsed_files.append(item)
                        return _validate_paths(parsed_files)
    except RunnerError:
        raise
    except Exception:
        # fall back to bullet list parsing
        pass

    # Fallback: bullet list (rare)
    files: list[str] = []
    for line in text.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            files.append(m.group("path"))
    if files:
        return _validate_paths(files)

    raise RunnerError("PREFLIGHT", "MANIFEST", "FILES not found in patch script")
