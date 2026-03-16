from __future__ import annotations

from pathlib import Path

from .payload_loader import exec_payload

exec_payload(globals(), Path(__file__).with_name("ipc_socket_payload.txt"))
