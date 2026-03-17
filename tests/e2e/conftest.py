from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = Path(__file__).resolve().parent

e2e_dir_str = str(E2E_DIR)
if e2e_dir_str not in sys.path:
    sys.path.insert(0, e2e_dir_str)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, *, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)

    raise RuntimeError(f"Timed out waiting for {url!r}. Last error: {last_error!r}")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _spawn_server(
    *,
    script_path: Path,
    host: str,
    port: int,
    readiness_url: str,
    log_path: Path,
    extra_env: dict[str, str] | None = None,
) -> Iterator[str]:
    log_file = log_path.open("wb")

    env = os.environ.copy()
    pythonpath = [str(REPO_ROOT), str(REPO_ROOT / "src"), str(REPO_ROOT / "scripts")]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["E2E_HOST"] = host
    env["E2E_PORT"] = str(port)
    env.setdefault("E2E_WEB_VERBOSITY", "0")
    if extra_env:
        env.update(extra_env)

    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_until_ready(readiness_url)
    except Exception as err:
        _terminate_process(process)
        log_file.flush()
        startup_log = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to start the e2e server. See {log_path}:\n{startup_log}"
        ) from err

    try:
        yield f"http://{host}:{port}"
    finally:
        _terminate_process(process)
        log_file.close()


@pytest.fixture(scope="session")
def e2e_web_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    existing = os.getenv("E2E_WEB_BASE_URL") or os.getenv("E2E_BASE_URL")
    if existing:
        yield existing.rstrip("/")
        return

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = int(os.getenv("E2E_PORT", "0")) or _pick_free_port()
    log_dir = tmp_path_factory.mktemp("playwright-e2e-web")
    state_dir = tmp_path_factory.mktemp("playwright-e2e-web-state")
    readiness_url = f"http://{host}:{port}/api/health"

    yield from _spawn_server(
        script_path=REPO_ROOT / "tests" / "e2e" / "_server_web_interface.py",
        host=host,
        port=port,
        readiness_url=readiness_url,
        log_path=log_dir / "web_interface.log",
        extra_env={"E2E_STATE_DIR": str(state_dir)},
    )


@pytest.fixture(scope="session")
def e2e_base_url(e2e_web_base_url: str) -> Iterator[str]:
    yield e2e_web_base_url


@pytest.fixture(scope="session")
def e2e_web_v3_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    existing = os.getenv("E2E_WEB_V3_BASE_URL")
    if existing:
        yield existing.rstrip("/")
        return

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = _pick_free_port()
    log_dir = tmp_path_factory.mktemp("playwright-e2e-web-v3")
    state_dir = tmp_path_factory.mktemp("playwright-e2e-web-v3-state")
    readiness_url = f"http://{host}:{port}/api/health"

    yield from _spawn_server(
        script_path=REPO_ROOT / "tests" / "e2e" / "_server_web_interface.py",
        host=host,
        port=port,
        readiness_url=readiness_url,
        log_path=log_dir / "web_interface_v3.log",
        extra_env={
            "E2E_STATE_DIR": str(state_dir),
            "E2E_IMPORT_WD_VERSION": "3",
        },
    )


@pytest.fixture(scope="session")
def e2e_patchhub_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    existing = os.getenv("E2E_PATCHHUB_BASE_URL")
    if existing:
        yield existing.rstrip("/")
        return

    host = os.getenv("E2E_HOST", "127.0.0.1")
    port = _pick_free_port()
    log_dir = tmp_path_factory.mktemp("playwright-e2e-patchhub")
    readiness_url = f"http://{host}:{port}/"

    yield from _spawn_server(
        script_path=REPO_ROOT / "tests" / "e2e" / "_server_patchhub.py",
        host=host,
        port=port,
        readiness_url=readiness_url,
        log_path=log_dir / "patchhub.log",
    )
