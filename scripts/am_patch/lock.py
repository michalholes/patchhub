from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover
    fcntl: ModuleType | None = None
else:
    fcntl = _fcntl


@dataclass
class FileLock:
    path: Path
    _fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        self._fd = fd
        if fcntl is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            self._fd = None
            raise RuntimeError(f"runner lock is held: {self.path}") from e

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if fcntl is not None:
                with contextlib.suppress(Exception):
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
