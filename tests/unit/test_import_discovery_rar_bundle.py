from __future__ import annotations

from importlib import import_module

from plugins.file_io.service import FileEntry, RootName

run_discovery = import_module("plugins.import.discovery").run_discovery


class _FakeFileService:
    def __init__(self, entries: list[FileEntry]) -> None:
        self._entries = entries

    def list_dir(
        self, root: RootName, rel_path: str = ".", *, recursive: bool = False
    ) -> list[FileEntry]:
        _ = (root, rel_path, recursive)
        return list(self._entries)


def test_discovery_classifies_rar_as_bundle() -> None:
    fs = _FakeFileService(
        [
            FileEntry(rel_path="sp.rar", is_dir=False, size=None, mtime=None),
        ]
    )

    items = run_discovery(fs, root="inbox", relative_path=".")

    assert items == [
        {
            "item_id": "root:inbox|path:sp.rar",
            "root": "inbox",
            "relative_path": "sp.rar",
            "kind": "bundle",
        }
    ]
