from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch.config import Policy
from am_patch.errors import RunnerCancelledError, RunnerError
from am_patch.ipc_socket import IpcController, resolve_socket_path
from am_patch.log import Logger
from am_patch.status import StatusReporter


@dataclass
class StartupLoggerIpc:
    logger: Logger
    ipc: IpcController | None


def build_startup_logger_and_ipc(
    *,
    cli: Any,
    policy: Policy,
    patch_dir: Path,
    log_path: Path,
    json_path: Path | None,
    status: StatusReporter,
    verbosity: str,
    log_level: str,
    symlink_path: Path,
) -> StartupLoggerIpc:
    logger = Logger(
        log_path=log_path,
        symlink_path=symlink_path,
        screen_level=verbosity,
        log_level=log_level,
        console_color=getattr(policy, "console_color", "auto"),
        symlink_enabled=policy.current_log_symlink_enabled,
        symlink_target_rel=Path(policy.patch_layout_logs_dir) / log_path.name,
        json_enabled=getattr(policy, "json_out", False),
        json_path=json_path,
        stage_provider=status.get_stage,
        run_timeout_s=policy.runner_subprocess_timeout_s,
    )

    def _emit_machine_heartbeat() -> None:
        logger.emit(
            severity="DEBUG",
            channel="DETAIL",
            kind="HEARTBEAT",
            message="HEARTBEAT\n",
            to_screen=False,
            to_log=False,
        )

    status.set_heartbeat_hook(_emit_machine_heartbeat)
    logger.set_screen_break_hook(status.break_line)

    ipc: IpcController | None = None
    startup_handshake_enabled = bool(getattr(policy, "ipc_handshake_enabled", False))
    startup_ready = False
    sock_path = resolve_socket_path(policy=policy, patch_dir=patch_dir, issue_id=cli.issue_id)
    if sock_path is not None:
        ipc = IpcController(
            socket_path=sock_path,
            issue_id=cli.issue_id,
            mode=cli.mode,
            status_provider=status,
            logger=logger,
            handshake_enabled=startup_handshake_enabled,
            handshake_wait_s=int(getattr(policy, "ipc_handshake_wait_s", 0) or 0),
        )
        ipc.start()
        if startup_handshake_enabled:
            startup_ready = ipc.wait_for_ready()

        def _ipc_hook(_kind: str, _stage: str) -> None:
            action = ipc.check_boundary(completed_step=_stage)
            if action == "pause_after_step":
                ipc.wait_if_paused()
            if action == "stop_after_step":
                raise RunnerError(
                    "INTERNAL",
                    "IPC",
                    f"stop_after_step reached: {_stage}",
                )
            st = ipc.snapshot()
            if bool(st.get("cancel")):
                raise RunnerCancelledError(
                    "INTERNAL",
                    f"cancelled ({action or 'cancel'})",
                )

        logger.set_ipc_hook(_ipc_hook)

    logger.emit(
        severity="INFO",
        channel="CORE",
        message=(
            f"START: issue={cli.issue_id or '(none)'} mode={cli.mode} "
            f"verbosity={verbosity} log_level={log_level}\n"
        ),
        summary=True,
        kind="START",
    )
    logger.emit_json_hello(
        issue_id=cli.issue_id,
        mode=cli.mode,
        verbosity=verbosity,
        log_level=log_level,
    )
    if startup_handshake_enabled and ipc is not None:
        msg = (
            "DEBUG: IPC startup handshake completed before START\n"
            if startup_ready
            else "DEBUG: IPC startup handshake timed out; continuing legacy IPC\n"
        )
        logger.emit(
            severity="DEBUG",
            channel="DETAIL",
            message=msg,
            kind="TEXT",
        )
    return StartupLoggerIpc(logger=logger, ipc=ipc)
