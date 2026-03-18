from __future__ import annotations

import ast
import re
from pathlib import Path

from .errors import RunnerError

_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<path>[^#\s]+)\s*$")


def _validate_paths(files: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for f in files:
        if not isinstance(f, str):
            raise RunnerError("PREFLIGHT", "MANIFEST", "FILES entries must be strings")
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
                        value = ast.literal_eval(node.value)
                        if not isinstance(value, list):
                            raise RunnerError("PREFLIGHT", "MANIFEST", "FILES must be a list")
                        return _validate_paths(list(value))
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
