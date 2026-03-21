from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from audiomason.core.config import ConfigResolver

ImportPlugin = import_module("plugins.import.plugin").ImportPlugin


class _FakeAudioProcessor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.bitrate = "128k"
        self.loudnorm = False
        self.split_chapters = False

    def plan_import_conversion(
        self,
        source: Path,
        output_dir: Path,
        *,
        chapters: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(f"audio.plan:{source.name}")
        return [{"source": source, "output": output_dir / f"{source.stem}.mp3", "order": 1}]

    async def _execute_plan(self, plan: list[dict[str, Any]]) -> list[Path]:
        outputs: list[Path] = []
        for item in plan:
            output = Path(item["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mp3")
            outputs.append(output)
            self.calls.append(f"audio.exec:{output.name}")
        return outputs


class _FakeCoverHandler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def discover_cover_candidates(
        self,
        directory: Path,
        *,
        audio_file: Path | None = None,
    ) -> list[dict[str, str]]:
        raise AssertionError("runner must not rediscover cover candidates")

    async def apply_cover_candidate(
        self,
        candidate: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> Path | None:
        self.calls.append(f"cover.apply:{candidate.get('candidate_id')}")
        if output_dir is None:
            return Path(str(candidate["path"]))
        output = output_dir / "cover.jpg"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"jpg")
        return output

    async def convert_to_jpeg(self, image_path: Path, quality: int = 95) -> Path:
        self.calls.append("cover.convert")
        return image_path

    async def embed_covers_batch(self, mp3_files: list[Path], cover_path: Path) -> None:
        self.calls.append("cover.embed")
        for mp3_file in mp3_files:
            mp3_file.write_bytes(mp3_file.read_bytes() + b"|cover")


class _FakeID3Tagger:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def write_tags(
        self,
        mp3_file: Path,
        tags: dict[str, Any],
        *,
        wipe_before_write: bool = True,
        preserve_cover: bool = True,
        file_index: int = 0,
    ) -> None:
        values = dict(tags.get("values") or {}) if isinstance(tags, dict) else {}
        title = str(values.get("title") or "")
        artist = str(values.get("artist") or "")
        track_start = tags.get("track_start") if isinstance(tags, dict) else None
        track = ""
        if track_start is not None:
            track = str(int(track_start) + file_index)
        self.calls.append(f"tags.write:{mp3_file.name}:{title}:{artist}:{track}")
        mp3_file.write_bytes(mp3_file.read_bytes() + b"|tags")


class _FakeLoader:
    def __init__(self, calls: list[str]) -> None:
        self._plugins = {
            "audio_processor": _FakeAudioProcessor(calls),
            "cover_handler": _FakeCoverHandler(calls),
            "id3_tagger": _FakeID3Tagger(calls),
        }

    def get_plugin(self, name: str) -> Any:
        return self._plugins[name]


def _make_plugin(tmp_path: Path) -> tuple[ImportPlugin, dict[str, Path]]:
    roots = {
        name: tmp_path / name for name in ("inbox", "stage", "outbox", "jobs", "config", "wizards")
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
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
    return ImportPlugin(resolver=resolver), roots


async def test_import_plugin_runs_phase2_process_contract_from_job_requests(
    tmp_path: Path,
) -> None:
    plugin, roots = _make_plugin(tmp_path)
    calls: list[str] = []
    loader = _FakeLoader(calls)

    source_dir = roots["inbox"] / "Shelf" / "RawBook"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "track01.m4a").write_bytes(b"audio")
    (source_dir / "cover.jpg").write_bytes(b"cover")

    session_dir = roots["wizards"] / "import" / "sessions" / "s1"
    session_dir.mkdir(parents=True, exist_ok=True)
    job_requests = {
        "job_type": "import.process",
        "job_version": 1,
        "session_id": "s1",
        "mode": "stage",
        "config_fingerprint": "cfg",
        "diagnostics_context": {"session_id": "s1"},
        "actions": [
            {
                "type": "import.book",
                "book_id": "book:1",
                "source": {"root": "inbox", "relative_path": "Shelf/RawBook"},
                "target": {"root": "stage", "relative_path": "Published/Canonical"},
                "authority": {
                    "book": {
                        "author_label": "Canonical Author",
                        "book_label": "Canonical Book",
                    },
                    "metadata_tags": {
                        "field_map": {
                            "title": "album",
                            "artist": "album_artist",
                        },
                        "values": {
                            "title": "Canonical Book",
                            "artist": "Canonical Author",
                        },
                    },
                    "publish": {
                        "root": "stage",
                        "relative_path": "Published/Canonical",
                    },
                },
                "capabilities": [
                    {"kind": "audio.import", "order": 10, "options": {}},
                    {
                        "kind": "cover.embed",
                        "order": 20,
                        "mode": "file",
                        "choice": {
                            "kind": "candidate",
                            "candidate_id": "file:cover.jpg",
                            "source_relative_path": "Shelf/RawBook",
                        },
                        "candidate": {
                            "kind": "file",
                            "candidate_id": "file:cover.jpg",
                            "apply_mode": "copy",
                            "path": "Shelf/RawBook/cover.jpg",
                            "source_relative_path": "Shelf/RawBook",
                        },
                    },
                    {
                        "kind": "metadata.tags",
                        "order": 30,
                        "field_map": {
                            "title": "album",
                            "artist": "album_artist",
                        },
                        "values": {
                            "title": "Canonical Book",
                            "artist": "Canonical Author",
                        },
                        "track_start": 7,
                    },
                    {
                        "kind": "publish.write",
                        "order": 40,
                        "root": "stage",
                        "relative_path": "Published/Canonical",
                        "overwrite": True,
                    },
                ],
            }
        ],
    }
    (session_dir / "job_requests.json").write_text(json.dumps(job_requests), encoding="utf-8")

    await plugin.run_process_contract(
        job_id="job-129",
        job_meta={"job_requests_path": "wizards:import/sessions/s1/job_requests.json"},
        plugin_loader=loader,
    )

    output_file = roots["stage"] / "Published" / "Canonical" / "track01.mp3"
    assert output_file.exists()
    assert output_file.read_bytes().endswith(b"|cover|tags")
    assert calls == [
        "audio.plan:track01.m4a",
        "audio.exec:track01.mp3",
        "cover.apply:file:cover.jpg",
        "cover.convert",
        "cover.embed",
        "tags.write:track01.mp3:Canonical Book:Canonical Author:7",
    ]
