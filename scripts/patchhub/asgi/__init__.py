"""PatchHub ASGI backend.

This package implements the PatchHub asynchronous backend.
"""

from __future__ import annotations

import sys


def _install_patchhub_alias() -> None:
    if "patchhub" in sys.modules:
        return
    parent_name, _, _ = __name__.rpartition(".")
    if not parent_name:
        return
    parent_module = sys.modules.get(parent_name)
    if parent_module is None:
        return
    if not hasattr(parent_module, "__path__"):
        return
    sys.modules.setdefault("patchhub", parent_module)


_install_patchhub_alias()
