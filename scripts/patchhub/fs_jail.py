from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class FsJailError(ValueError):
    pass


def _is_ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class FsJail:
    repo_root: Path
    patches_root_rel: str
    crud_allowlist: list[str]
    allow_crud: bool

    def patches_root(self) -> Path:
        return (self.repo_root / self.patches_root_rel).resolve()

    def lock_path(self) -> Path:
        return self.patches_root() / "am_patch.lock"

    def resolve_rel(self, rel_path: str) -> Path:
        if rel_path.startswith("/"):
            raise FsJailError("Path must be repo-relative")
        if "\\" in rel_path:
            raise FsJailError("Backslashes are not allowed")
        if not _is_ascii(rel_path):
            raise FsJailError("Non-ASCII path is not allowed")

        root = self.patches_root()
        candidate = (root / rel_path).resolve()
        if root not in candidate.parents and candidate != root:
            raise FsJailError("Path escapes patches root")
        return candidate

    def _allow_dir(self, rel_path: str) -> bool:
        norm = rel_path.strip("/")
        if norm == "":
            return "" in self.crud_allowlist
        if "/" not in norm:
            return ("" in self.crud_allowlist) or (norm in self.crud_allowlist)
        top = norm.split("/")[0]
        return top in self.crud_allowlist

    def assert_crud_allowed(self, rel_path: str) -> None:
        if not self.allow_crud:
            raise FsJailError("CRUD is disabled")
        if not self._allow_dir(rel_path):
            raise FsJailError("Path is not allowlisted")

    def ensure_dirs(self, rel_dir: str) -> Path:
        p = self.resolve_rel(rel_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def list_dir(path: Path) -> list[dict[str, str | int | bool]]:
    items: list[dict[str, str | int | bool]] = []
    for entry in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        st = entry.stat()
        items.append(
            {
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": int(st.st_size),
                "mtime": int(st.st_mtime),
            }
        )
    return items


def safe_rename(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
