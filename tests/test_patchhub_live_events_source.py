# ruff: noqa: E402
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import patchhub.asgi.job_events_live_source as live_source_mod
from patchhub.asgi.job_event_broker import JobEventBroker
from patchhub.asgi.job_events_live_source import (
    _read_tail_snapshot,
    stream_job_events_live_source,
)


class TestPatchhubLiveEventsSource(unittest.IsolatedAsyncioTestCase):
    async def test_active_job_waits_for_broker_and_switches_to_live(self) -> None:
        with TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "job.jsonl"
            jsonl_path.write_text(
                '{"type":"log","msg":"queued"}\n',
                encoding="utf-8",
            )
            status = {"value": "queued"}
            broker_ref: dict[str, JobEventBroker | None] = {"value": None}

            async def job_status() -> str | None:
                return str(status["value"])

            async def get_broker() -> JobEventBroker | None:
                return broker_ref["value"]

            async def historical_stream():
                raise AssertionError("historical fallback must not run for active jobs")
                yield b""

            async def publish_live() -> None:
                await asyncio.sleep(0.05)
                broker = JobEventBroker()
                broker_ref["value"] = broker
                await asyncio.sleep(0.05)
                broker.publish('{"type":"log","msg":"live"}', 999)
                await asyncio.sleep(0.01)
                status["value"] = "success"
                broker.close()

            task = asyncio.create_task(publish_live())
            chunks: list[bytes] = []
            async for chunk in stream_job_events_live_source(
                job_id="job-500-live",
                jsonl_path=jsonl_path,
                in_memory_job=True,
                job_status=job_status,
                get_broker=get_broker,
                historical_stream=historical_stream,
                broker_poll_interval_s=0.01,
            ):
                chunks.append(chunk)
            await task

        payload = b"".join(chunks).decode("utf-8")
        self.assertIn('data: {"type":"log","msg":"queued"}', payload)
        self.assertIn('data: {"type":"log","msg":"live"}', payload)
        self.assertIn("event: end", payload)
        self.assertIn('"status": "success"', payload)

    async def test_connect_gap_event_is_replayed_exactly_once(self) -> None:
        with TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "job.jsonl"
            queued_line = '{"type":"log","msg":"queued"}'
            live_line = '{"type":"log","msg":"during_tail"}'
            jsonl_path.write_text(queued_line + "\n", encoding="utf-8")
            snapshot_end = jsonl_path.stat().st_size
            live_end = snapshot_end + len(live_line.encode("utf-8")) + 1
            status = {"value": "running"}
            broker = JobEventBroker()

            async def job_status() -> str | None:
                return str(status["value"])

            async def get_broker() -> JobEventBroker | None:
                return broker

            async def historical_stream():
                raise AssertionError("historical fallback must not run for active jobs")
                yield b""

            def fake_read_tail_snapshot(
                path: Path,
                lines: int,
                *,
                max_bytes: int = 8_388_608,
            ) -> tuple[str, int]:
                del path, lines, max_bytes
                broker.publish(live_line, live_end)
                return queued_line, snapshot_end

            async def finish_stream() -> None:
                await asyncio.sleep(0.02)
                status["value"] = "success"
                broker.close()

            task = asyncio.create_task(finish_stream())
            with patch.object(
                live_source_mod,
                "_read_tail_snapshot",
                side_effect=fake_read_tail_snapshot,
            ):
                chunks = [
                    chunk
                    async for chunk in stream_job_events_live_source(
                        job_id="job-503-gap",
                        jsonl_path=jsonl_path,
                        in_memory_job=True,
                        job_status=job_status,
                        get_broker=get_broker,
                        historical_stream=historical_stream,
                        broker_poll_interval_s=0.01,
                    )
                ]
            await task

        payload = b"".join(chunks).decode("utf-8")
        self.assertEqual(payload.count(f"data: {live_line}"), 1)
        self.assertIn(f"data: {queued_line}", payload)
        self.assertIn("event: end", payload)

    async def test_disk_only_job_uses_historical_stream(self) -> None:
        with TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "job.jsonl"
            jsonl_path.write_text("", encoding="utf-8")
            seen: list[str] = []

            async def job_status() -> str | None:
                return "success"

            async def get_broker() -> JobEventBroker | None:
                raise AssertionError("disk-only jobs must not query live broker")

            async def historical_stream():
                seen.append("historical")
                yield b'data: {"type":"log","msg":"from_history"}\n\n'
                yield b'event: end\ndata: {"reason": "job_completed"}\n\n'

            chunks = [
                chunk
                async for chunk in stream_job_events_live_source(
                    job_id="job-500-history",
                    jsonl_path=jsonl_path,
                    in_memory_job=False,
                    job_status=job_status,
                    get_broker=get_broker,
                    historical_stream=historical_stream,
                )
            ]

        self.assertEqual(seen, ["historical"])
        payload = b"".join(chunks).decode("utf-8")
        self.assertIn("from_history", payload)
        self.assertIn("event: end", payload)

    async def test_active_job_emits_canceled_end_status(self) -> None:
        with TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "job.jsonl"
            jsonl_path.write_text('{"type":"log","msg":"queued"}\n', encoding="utf-8")
            status = {"value": "running"}
            broker = JobEventBroker()

            async def job_status() -> str | None:
                return str(status["value"])

            async def get_broker() -> JobEventBroker | None:
                return broker

            async def historical_stream():
                raise AssertionError("historical fallback must not run for active jobs")
                yield b""

            async def finish_stream() -> None:
                await asyncio.sleep(0.02)
                status["value"] = "canceled"
                broker.close()

            task = asyncio.create_task(finish_stream())
            chunks = [
                chunk
                async for chunk in stream_job_events_live_source(
                    job_id="job-652-canceled",
                    jsonl_path=jsonl_path,
                    in_memory_job=True,
                    job_status=job_status,
                    get_broker=get_broker,
                    historical_stream=historical_stream,
                    broker_poll_interval_s=0.01,
                )
            ]
            await task

        payload = b"".join(chunks).decode("utf-8")
        self.assertIn("event: end", payload)
        self.assertIn('"status": "canceled"', payload)

    def test_read_tail_snapshot_clamps_to_20000_lines(self) -> None:
        with TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "job.jsonl"
            jsonl_path.write_text(
                "\n".join(f'{{"type":"log","msg":"{idx}"}}' for idx in range(20_005)) + "\n",
                encoding="utf-8",
            )

            tail, _offset = _read_tail_snapshot(jsonl_path, 99_999)

        lines = tail.splitlines()
        self.assertEqual(len(lines), 20_000)
        self.assertEqual(lines[0], '{"type":"log","msg":"5"}')
        self.assertEqual(lines[-1], '{"type":"log","msg":"20004"}')
