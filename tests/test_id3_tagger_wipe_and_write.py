"""Issue 125: deterministic wipe-before-write tagging surfaces."""

from __future__ import annotations

from pathlib import Path

from plugins.id3_tagger.plugin import ID3TaggerPlugin

from audiomason.core import ProcessingContext


def test_build_context_tags_returns_canonical_order_and_values(tmp_path: Path) -> None:
    plugin = ID3TaggerPlugin()
    context = ProcessingContext(
        id="ctx-1",
        source=tmp_path / "book.m4b",
        title="Book Title",
        author="Author Name",
        year=2024,
        genre="Fiction",
        narrator="Narrator Name",
        series="Series Name",
        series_number=3,
    )

    tags = plugin.build_context_tags(context)

    assert list(tags.items()) == [
        ("title", "Book Title"),
        ("artist", "Author Name"),
        ("album", "Book Title"),
        ("album_artist", "Author Name"),
        ("date", "2024"),
        ("genre", "Fiction"),
        ("composer", "Narrator Name"),
        ("comment", "Series Name #3"),
    ]


def test_build_write_tags_command_wipes_before_write_and_preserves_cover(
    tmp_path: Path,
) -> None:
    plugin = ID3TaggerPlugin()
    source = tmp_path / "book.mp3"
    output = tmp_path / "book.tagged.mp3"

    cmd = plugin.build_write_tags_command(
        source,
        output,
        {
            "genre": "Fiction",
            "artist": "Author Name",
            "title": "Book Title",
        },
    )

    assert cmd[:12] == [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-map_metadata",
        "-1",
    ]
    assert [cmd[i + 1] for i, value in enumerate(cmd) if value == "-metadata"] == [
        "title=Book Title",
        "artist=Author Name",
        "genre=Fiction",
    ]
    assert cmd[-1] == str(output)


def test_build_write_tags_command_resolves_capability_field_map_and_track_start(
    tmp_path: Path,
) -> None:
    plugin = ID3TaggerPlugin()
    source = tmp_path / "chapter.mp3"
    output = tmp_path / "chapter.tagged.mp3"

    cmd = plugin.build_write_tags_command(
        source,
        output,
        {
            "field_map": {
                "title": "book_title",
                "artist": "author",
                "album": "book_title",
                "album_artist": "author",
            },
            "values": {
                "book_title": "Book Title",
                "author": "Author Name",
                "genre": "Fiction",
            },
            "track_start": 7,
        },
        file_index=2,
    )

    assert [cmd[i + 1] for i, value in enumerate(cmd) if value == "-metadata"] == [
        "title=Book Title",
        "artist=Author Name",
        "album=Book Title",
        "album_artist=Author Name",
        "genre=Fiction",
        "track=9",
    ]
