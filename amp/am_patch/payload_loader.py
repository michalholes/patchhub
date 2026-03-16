from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any


def exec_payload(module_globals: dict[str, Any], payload_path: Path) -> None:
    source = payload_path.read_text(encoding="utf-8")
    code = compile(source, str(payload_path), "exec")
    exec(code, module_globals, module_globals)
