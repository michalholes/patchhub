"""Tests for atomic JSONL persistence in import storage."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from audiomason.core.config import ConfigResolver

FileService = import_module("plugins.file_io.service.service").FileService
RootName = import_module("plugins.file_io.service").RootName
append_jsonl = import_module("plugins.import.storage").append_jsonl


def _make_fs(tmp_path: Path):
    roots = {
        "inbox": tmp_path / "inbox",
        "stage": tmp_path / "stage",
        "outbox": tmp_path / "outbox",
        "jobs": tmp_path / "jobs",
        "config": tmp_path / "config",
        "wizards": tmp_path / "wizards",
    }
    defaults = {
        "file_io": {
            "roots": {
                "inbox_dir": str(roots["inbox"]),
                "stage_dir": str(roots["stage"]),
                "outbox_dir": str(roots["outbox"]),
                "jobs_dir": str(roots["jobs"]),
                "config_dir": str(roots["config"]),
                "wizards_dir": str(roots["wizards"]),
            }
        },
        "output_dir": str(roots["outbox"]),
        "diagnostics": {"enabled": False},
    }
    resolver = ConfigResolver(
        cli_args=defaults,
        defaults=defaults,
        user_config_path=tmp_path / "no_user_config.yaml",
        system_config_path=tmp_path / "no_system_config.yaml",
    )
    return FileService.from_resolver(resolver)


def test_append_jsonl_creates_file_atomically(tmp_path: Path) -> None:
    fs = _make_fs(tmp_path)
    rel = "import/sessions/s1/decisions.jsonl"

    append_jsonl(fs, RootName.WIZARDS, rel, {"a": 1})

    assert fs.exists(RootName.WIZARDS, rel)
    with fs.open_read(RootName.WIZARDS, rel) as f:
        lines = f.read().decode("utf-8").splitlines()

    assert lines == [json.dumps({"a": 1}, ensure_ascii=True, separators=(",", ":"), sort_keys=True)]


def test_append_jsonl_appends_two_lines(tmp_path: Path) -> None:
    fs = _make_fs(tmp_path)
    rel = "import/sessions/s1/decisions.jsonl"

    append_jsonl(fs, RootName.WIZARDS, rel, {"a": 1})
    append_jsonl(fs, RootName.WIZARDS, rel, {"b": 2})

    with fs.open_read(RootName.WIZARDS, rel) as f:
        lines = f.read().decode("utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}
