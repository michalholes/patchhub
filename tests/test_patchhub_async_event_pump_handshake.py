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

from patchhub.asgi.async_event_pump import EventPumpCommandChannel, start_event_pump


class TestPatchhubAsyncEventPumpHandshake(unittest.IsolatedAsyncioTestCase):
    async def test_persists_connected_and_eos_without_internal_reply_lines(self) -> None:
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
                '{"type":"log","msg":"tail"}',
                '{"type":"control","event":"eos","seq":7}',
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

    async def test_cancel_uses_existing_connection_and_preserves_stream(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "job.sock"
            jsonl_path = root / "job.jsonl"
            published: list[str] = []
            received_cmds: list[dict[str, object]] = []
            connection_count = 0
            command_channel = EventPumpCommandChannel()
            pump_started = asyncio.Event()

            async def handle(
                reader: asyncio.StreamReader,
                writer: asyncio.StreamWriter,
            ) -> None:
                nonlocal connection_count
                connection_count += 1
                writer.write(b'{"type":"control","event":"connected"}\n')
                await writer.drain()

                ready_raw = await reader.readline()
                ready_obj = json.loads(ready_raw.decode("utf-8"))
                received_cmds.append(ready_obj)
                writer.write(
                    b'{"type":"reply","cmd":"ready","cmd_id":"patchhub_ready",'
                    b'"ok":true,"data":{"ready":true}}\n'
                )
                writer.write(b'{"type":"log","msg":"before-cancel"}\n')
                await writer.drain()
                pump_started.set()

                cancel_raw = await reader.readline()
                cancel_obj = json.loads(cancel_raw.decode("utf-8"))
                received_cmds.append(cancel_obj)
                writer.write(
                    (
                        json.dumps(
                            {
                                "type": "reply",
                                "cmd": "cancel",
                                "cmd_id": str(cancel_obj["cmd_id"]),
                                "ok": True,
                                "data": {"accepted": True},
                            },
                            ensure_ascii=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                )
                writer.write(b'{"type":"log","msg":"after-cancel"}\n')
                writer.write(b'{"type":"control","event":"eos","seq":11}\n')
                await writer.drain()

                drain_raw = await reader.readline()
                drain_obj = json.loads(drain_raw.decode("utf-8"))
                received_cmds.append(drain_obj)
                writer.write(
                    b'{"type":"reply","cmd":"drain_ack",'
                    b'"cmd_id":"patchhub_drain_ack_11",'
                    b'"ok":true,"data":{"seq":11}}\n'
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_unix_server(handle, path=str(socket_path))
            try:
                pump_task = asyncio.create_task(
                    start_event_pump(
                        socket_path=str(socket_path),
                        jsonl_path=jsonl_path,
                        publish=lambda line, end: published.append(line),
                        command_channel=command_channel,
                    )
                )
                await asyncio.wait_for(pump_started.wait(), timeout=1.0)
                self.assertTrue(
                    await command_channel.send(
                        cmd="cancel",
                        args={},
                        cmd_id_prefix="patchhub_test_cancel",
                    )
                )
                await pump_task
            finally:
                server.close()
                await server.wait_closed()

            lines = jsonl_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(connection_count, 1)
        self.assertEqual(
            lines,
            [
                '{"type":"control","event":"connected"}',
                '{"type":"log","msg":"before-cancel"}',
                '{"type":"log","msg":"after-cancel"}',
                '{"type":"control","event":"eos","seq":11}',
            ],
        )
        self.assertEqual(published, lines)
        self.assertEqual(received_cmds[0]["cmd"], "ready")
        self.assertEqual(received_cmds[1]["cmd"], "cancel")
        self.assertEqual(received_cmds[2]["cmd"], "drain_ack")
