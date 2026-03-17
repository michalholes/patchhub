# ruff: noqa: E402
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from patchhub.asgi.async_event_pump import start_event_pump


class TestPatchhubAsyncEventPumpHandshake(unittest.IsolatedAsyncioTestCase):
    async def test_persists_connected_reply_and_eos_then_sends_drain_ack(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "job.sock"
            jsonl_path = root / "job.jsonl"
            published: list[tuple[str, int]] = []
            received_cmds: list[dict[str, object]] = []

            async def handle(
                reader: asyncio.StreamReader,
                writer: asyncio.StreamWriter,
            ) -> None:
                writer.write(b'{"type":"control","event":"connected"}\n')
                await writer.drain()

                ready_raw = await reader.readline()
                ready_obj = json.loads(ready_raw.decode("utf-8"))
                received_cmds.append(ready_obj)
                writer.write(
                    b'{"type":"reply","cmd":"ready","cmd_id":"patchhub_ready",'
                    b'"ok":true,"data":{"ready":true}}\n'
                )
                writer.write(b'{"type":"log","msg":"tail"}\n')
                writer.write(b'{"type":"control","event":"eos","seq":7}\n')
                await writer.drain()

                drain_raw = await reader.readline()
                drain_obj = json.loads(drain_raw.decode("utf-8"))
                received_cmds.append(drain_obj)
                writer.write(
                    b'{"type":"reply","cmd":"drain_ack",'
                    b'"cmd_id":"patchhub_drain_ack_7",'
                    b'"ok":true,"data":{"seq":7}}\n'
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_unix_server(handle, path=str(socket_path))
            try:
                await start_event_pump(
                    socket_path=str(socket_path),
                    jsonl_path=jsonl_path,
                    publish=lambda line, end: published.append((line, end)),
                )
            finally:
                server.close()
                await server.wait_closed()

            lines = jsonl_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            lines,
            [
                '{"type":"control","event":"connected"}',
                (
                    '{"type":"reply","cmd":"ready","cmd_id":"patchhub_ready",'
                    '"ok":true,"data":{"ready":true}}'
                ),
                '{"type":"log","msg":"tail"}',
                '{"type":"control","event":"eos","seq":7}',
                (
                    '{"type":"reply","cmd":"drain_ack",'
                    '"cmd_id":"patchhub_drain_ack_7",'
                    '"ok":true,"data":{"seq":7}}'
                ),
            ],
        )
        self.assertEqual([line for line, _ in published], lines)
        self.assertEqual(received_cmds[0]["cmd"], "ready")
        self.assertEqual(received_cmds[0]["cmd_id"], "patchhub_ready")
        self.assertEqual(received_cmds[1]["cmd"], "drain_ack")
        self.assertEqual(received_cmds[1]["cmd_id"], "patchhub_drain_ack_7")
        self.assertEqual(received_cmds[1]["args"], {"seq": 7})

    async def test_missing_reply_does_not_abort_raw_capture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "job.sock"
            jsonl_path = root / "job.jsonl"

            async def handle(
                reader: asyncio.StreamReader,
                writer: asyncio.StreamWriter,
            ) -> None:
                writer.write(b'{"type":"control","event":"connected"}\n')
                await writer.drain()

                await reader.readline()
                writer.write(b'{"type":"log","msg":"tail"}\n')
                writer.write(b'{"type":"control","event":"eos","seq":9}\n')
                await writer.drain()

                await reader.readline()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_unix_server(handle, path=str(socket_path))
            try:
                await start_event_pump(
                    socket_path=str(socket_path),
                    jsonl_path=jsonl_path,
                    publish=None,
                )
            finally:
                server.close()
                await server.wait_closed()

            lines = jsonl_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            lines,
            [
                '{"type":"control","event":"connected"}',
                '{"type":"log","msg":"tail"}',
                '{"type":"control","event":"eos","seq":9}',
            ],
        )
