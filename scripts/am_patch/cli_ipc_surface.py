from __future__ import annotations

import argparse


def add_ipc_override_args(
    p: argparse.ArgumentParser,
    *,
    append_override: type[argparse.Action],
) -> None:
    p.add_argument("--ipc-socket", action=append_override, key="ipc_socket_path", dest="overrides")
    p.add_argument(
        "--no-ipc-socket",
        action=append_override,
        key="ipc_socket_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    p.add_argument(
        "--ipc-socket-mode",
        action=append_override,
        key="ipc_socket_mode",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-base-dir",
        action=append_override,
        key="ipc_socket_base_dir",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-name-template",
        action=append_override,
        key="ipc_socket_name_template",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-cleanup-delay-success-s",
        action=append_override,
        key="ipc_socket_cleanup_delay_success_s",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-cleanup-delay-failure-s",
        action=append_override,
        key="ipc_socket_cleanup_delay_failure_s",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-on-startup-exists",
        action=append_override,
        key="ipc_socket_on_startup_exists",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-socket-on-startup-wait-s",
        action=append_override,
        key="ipc_socket_on_startup_wait_s",
        dest="overrides",
    )
    p.add_argument(
        "--ipc-handshake",
        action=append_override,
        key="ipc_handshake_enabled",
        const_value="true",
        dest="overrides",
        nargs=0,
    )
    p.add_argument(
        "--no-ipc-handshake",
        action=append_override,
        key="ipc_handshake_enabled",
        const_value="false",
        dest="overrides",
        nargs=0,
    )
    p.add_argument(
        "--ipc-handshake-wait-s",
        action=append_override,
        key="ipc_handshake_wait_s",
        dest="overrides",
    )
