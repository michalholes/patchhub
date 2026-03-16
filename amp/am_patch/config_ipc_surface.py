from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import RunnerError

IPC_NONNEGATIVE_IPC_INT_KEYS = (
    "ipc_socket_cleanup_delay_success_s",
    "ipc_socket_cleanup_delay_failure_s",
    "ipc_socket_on_startup_wait_s",
    "ipc_handshake_wait_s",
)


def apply_ipc_cfg_surface(
    p: Any,
    cfg: dict[str, Any],
    *,
    as_bool: Callable[[dict[str, Any], str, bool], bool],
    mark_cfg: Callable[[Any, dict[str, Any], str], None],
) -> None:
    p.ipc_socket_enabled = as_bool(cfg, "ipc_socket_enabled", p.ipc_socket_enabled)
    mark_cfg(p, cfg, "ipc_socket_enabled")
    p.ipc_socket_mode = str(cfg.get("ipc_socket_mode", p.ipc_socket_mode))
    mark_cfg(p, cfg, "ipc_socket_mode")
    p.ipc_socket_name_template = str(
        cfg.get("ipc_socket_name_template", p.ipc_socket_name_template)
    )
    mark_cfg(p, cfg, "ipc_socket_name_template")
    p.ipc_socket_on_startup_exists = str(
        cfg.get("ipc_socket_on_startup_exists", p.ipc_socket_on_startup_exists)
    )
    mark_cfg(p, cfg, "ipc_socket_on_startup_exists")
    if p.ipc_socket_on_startup_exists not in ("fail", "wait_then_fail", "unlink_if_stale"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            "ipc_socket_on_startup_exists must be fail|wait_then_fail|unlink_if_stale",
        )
    p.ipc_handshake_enabled = as_bool(
        cfg,
        "ipc_handshake_enabled",
        p.ipc_handshake_enabled,
    )
    mark_cfg(p, cfg, "ipc_handshake_enabled")
