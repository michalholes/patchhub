"""Issue 138: cover_handler parity candidate surfaces."""

from __future__ import annotations

import asyncio
from pathlib import Path

from plugins.cover_handler.plugin import CoverHandlerPlugin


def test_discover_cover_candidates_orders_named_generic_and_embedded(
    tmp_path: Path,
) -> None:
    plugin = CoverHandlerPlugin()
    source_dir = tmp_path / "book"
    source_dir.mkdir()
    for name in ["folder.png", "cover.jpeg", "zzz.jpg", "aaa.webp"]:
        (source_dir / name).write_bytes(name.encode("utf-8"))
    audio_file = source_dir / "book.m4a"
    audio_file.write_bytes(b"audio")

    candidates = plugin.discover_cover_candidates(
        source_dir,
        audio_file=audio_file,
        group_root="group",
        stage_root="stage",
    )

    ordered = [(item["kind"], Path(item["path"]).name, item["apply_mode"]) for item in candidates]
    assert ordered == [
        ("file", "cover.jpeg", "copy"),
        ("file", "folder.png", "copy"),
        ("file", "aaa.webp", "copy"),
        ("file", "zzz.jpg", "copy"),
        ("embedded", "book.m4a", "extract_embedded"),
    ]
    assert candidates[0]["root_name"] == "group"
    assert candidates[0]["mime_type"] == "image/jpeg"
    assert candidates[1]["mime_type"] == "image/png"
    assert candidates[2]["cache_key"] == "file:aaa.webp"
    assert candidates[-1]["cache_key"] == "embedded:book.m4a"


def test_discover_cover_candidates_embedded_only_when_no_file_cover(
    tmp_path: Path,
) -> None:
    plugin = CoverHandlerPlugin()
    source_dir = tmp_path / "book"
    source_dir.mkdir()
    audio_file = source_dir / "book.mp3"
    audio_file.write_bytes(b"audio")

    candidates = plugin.discover_cover_candidates(source_dir, audio_file=audio_file)

    assert len(candidates) == 1
    assert candidates[0]["kind"] == "embedded"
    assert candidates[0]["candidate_id"] == "embedded:book.mp3"
    assert candidates[0]["apply_mode"] == "extract_embedded"
    assert candidates[0]["path"] == str(audio_file)
    assert candidates[0]["mime_type"] == "image/jpeg"


def test_build_embedded_extract_commands_for_m4a_has_fallback(tmp_path: Path) -> None:
    plugin = CoverHandlerPlugin()
    audio_file = tmp_path / "book.m4a"
    output = tmp_path / "cover.jpg"

    commands = plugin.build_embedded_extract_commands(audio_file, output)

    assert len(commands) == 2
    assert commands[0][-3:] == ["-c:v", "copy", str(output)]
    assert commands[1][-4:] == ["-map", "0:v:0", "-frames:v", "1", str(output)][-4:]


def test_apply_cover_candidate_copies_file_to_output_dir(tmp_path: Path) -> None:
    plugin = CoverHandlerPlugin()
    source = tmp_path / "cover.png"
    source.write_bytes(b"cover-bytes")
    output_dir = tmp_path / "out"

    copied = asyncio.run(
        plugin.apply_cover_candidate(
            {
                "kind": "file",
                "candidate_id": "file:cover.png",
                "apply_mode": "copy",
                "path": str(source),
            },
            output_dir=output_dir,
        )
    )

    assert copied == output_dir / "cover.png"
    assert copied is not None
    assert copied.read_bytes() == b"cover-bytes"


def test_build_url_candidate_prefers_group_root_and_resolves_mime_and_cache() -> None:
    plugin = CoverHandlerPlugin()

    candidate = plugin.build_url_candidate(
        "https://example.test/cover",
        mime_type="image/webp; charset=binary",
        cache_key="book-123",
        group_root="group",
        stage_root="stage",
    )

    assert candidate == {
        "kind": "url",
        "candidate_id": candidate["candidate_id"],
        "apply_mode": "download",
        "url": "https://example.test/cover",
        "mime_type": "image/webp",
        "cache_key": "book-123",
        "root_name": "group",
    }
    assert candidate["candidate_id"].startswith("url:")


def test_download_output_path_uses_cache_key_and_mime_extension(tmp_path: Path) -> None:
    plugin = CoverHandlerPlugin()

    output = plugin._download_output_path(
        tmp_path,
        url="https://example.test/no-extension",
        mime_type="image/png",
        cache_key="cache-book-1",
    )

    assert output.parent == tmp_path
    assert output.suffix == ".png"
    assert output.name.startswith("cover_cache_")
