from __future__ import annotations

import site
import sys
from pathlib import Path


def external_bind_paths(*, repo_root: Path) -> list[Path]:
    if _interpreter_is_inside_repo(Path(sys.executable), repo_root=repo_root):
        return []
    return _existing_user_site_paths(repo_root=repo_root)


def _existing_user_site_paths(*, repo_root: Path) -> list[Path]:
    user_site = site.getusersitepackages()
    candidates = [user_site] if isinstance(user_site, str) else list(user_site)
    resolved_root = repo_root.resolve()
    seen: set[Path] = set()
    paths: list[Path] = []
    for value in candidates:
        candidate = Path(str(value))
        if not candidate.is_absolute() or not candidate.exists():
            continue
        resolved = candidate.resolve()
        if _path_is_under_root(resolved, resolved_root) or resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)
    return paths


def _interpreter_is_inside_repo(path: Path, *, repo_root: Path) -> bool:
    if not path.is_absolute():
        return False
    return _path_is_under_root(path.resolve(), repo_root.resolve())


def _path_is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
