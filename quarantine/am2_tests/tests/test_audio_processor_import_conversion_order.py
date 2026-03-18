"""Issue 140: audio_processor import conversion parity surfaces."""

from __future__ import annotations

from pathlib import Path

from plugins.audio_processor.plugin import AudioProcessorPlugin


def test_plan_import_conversion_targets_mp3_for_supported_import_formats(
    tmp_path: Path,
) -> None:
    plugin = AudioProcessorPlugin({"split_chapters": False})

    planned = [
        plugin.plan_import_conversion(tmp_path / f"book{suffix}", tmp_path)
        for suffix in (".m4a", ".m4b", ".opus")
    ]

    assert [plan[0]["source_format"] for plan in planned] == [".m4a", ".m4b", ".opus"]
    assert [plan[0]["target_format"] for plan in planned] == [".mp3", ".mp3", ".mp3"]
    assert [Path(plan[0]["output"]).suffix for plan in planned] == [
        ".mp3",
        ".mp3",
        ".mp3",
    ]


def test_plan_import_conversion_sorts_split_chapter_order_for_m4b(
    tmp_path: Path,
) -> None:
    plugin = AudioProcessorPlugin({"split_chapters": True, "loudnorm": True})
    source = tmp_path / "book.m4b"
    chapters = [
        {"start_time": "12.5", "end_time": "30.0"},
        {"start_time": "0.0", "end_time": "12.5"},
    ]

    plan = plugin.plan_import_conversion(source, tmp_path, chapters=chapters)

    assert [(item["operation"], item["chapter_index"]) for item in plan] == [
        ("split_chapter", 1),
        ("split_chapter", 2),
    ]
    assert [(item["start_time"], item["end_time"]) for item in plan] == [
        (0.0, 12.5),
        (12.5, 30.0),
    ]
    assert [Path(item["output"]).name for item in plan] == ["01.mp3", "02.mp3"]
    assert [item["source_format"] for item in plan] == [".m4b", ".m4b"]
    assert [item["target_format"] for item in plan] == [".mp3", ".mp3"]
    assert all(item["loudnorm"] is True for item in plan)


def test_build_split_command_keeps_seek_timing_and_loudnorm_order(
    tmp_path: Path,
) -> None:
    plugin = AudioProcessorPlugin({"split_chapters": True, "loudnorm": True})
    plan = plugin.plan_import_conversion(
        tmp_path / "book.m4a",
        tmp_path,
        chapters=[
            {"start_time": "5.0", "end_time": "15.0"},
            {"start_time": "15.0", "end_time": "25.0"},
        ],
    )

    cmd = plugin.build_conversion_command(plan[0])

    assert cmd[:12] == [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "5.0",
        "-i",
        str(tmp_path / "book.m4a"),
        "-t",
        "10.0",
    ]
    assert cmd[12] == "-vn"
    assert cmd[cmd.index("-af") + 1] == "loudnorm=I=-16:LRA=11:TP=-1.5"
    assert cmd.index("-af") < cmd.index("-codec:a")
    assert cmd[-1] == str(tmp_path / "01.mp3")


def test_build_conversion_command_keeps_loudnorm_and_codec_order(
    tmp_path: Path,
) -> None:
    plugin = AudioProcessorPlugin({"loudnorm": True})
    action = plugin.plan_import_conversion(tmp_path / "book.opus", tmp_path)[0]

    cmd = plugin.build_conversion_command(action)

    assert cmd[:8] == [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(tmp_path / "book.opus"),
    ]
    assert cmd[cmd.index("-af") + 1] == "loudnorm=I=-16:LRA=11:TP=-1.5"
    assert cmd.index("-af") < cmd.index("-codec:a")
    assert cmd[-1] == str(tmp_path / "book.mp3")
