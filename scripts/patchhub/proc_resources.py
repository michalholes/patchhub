from __future__ import annotations

import os
from typing import Any


def snapshot() -> dict[str, Any]:
    process = _process_snapshot()
    host = _host_snapshot()
    return {"process": process, "host": host}


def _process_snapshot() -> dict[str, Any]:
    rss_bytes = _rss_bytes()
    cpu_user_seconds, cpu_system_seconds = _cpu_times_seconds()
    return {
        "rss_bytes": int(rss_bytes),
        "cpu_user_seconds": float(cpu_user_seconds),
        "cpu_system_seconds": float(cpu_system_seconds),
    }


def _host_snapshot() -> dict[str, Any]:
    loadavg_1, loadavg_5, loadavg_15 = _loadavg()
    mem_total_bytes, mem_available_bytes = _mem_bytes()
    net_rx_bytes_total, net_tx_bytes_total = _net_bytes_total()
    return {
        "loadavg_1": float(loadavg_1),
        "loadavg_5": float(loadavg_5),
        "loadavg_15": float(loadavg_15),
        "mem_total_bytes": int(mem_total_bytes),
        "mem_available_bytes": int(mem_available_bytes),
        "net_rx_bytes_total": int(net_rx_bytes_total),
        "net_tx_bytes_total": int(net_tx_bytes_total),
    }


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _rss_bytes() -> int:
    txt = _read_text("/proc/self/status")
    # Example: 'VmRSS:\t  12345 kB'
    for line in txt.splitlines():
        if not line.startswith("VmRSS:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            break
        try:
            kb = int(parts[1])
        except Exception:
            break
        return kb * 1024
    return 0


def _cpu_times_seconds() -> tuple[float, float]:
    txt = _read_text("/proc/self/stat").strip()
    if not txt:
        return (0.0, 0.0)

    parts = txt.split()
    # utime/stime are fields 14/15 (1-indexed).
    if len(parts) < 15:
        return (0.0, 0.0)

    try:
        uticks = int(parts[13])
        sticks = int(parts[14])
    except Exception:
        return (0.0, 0.0)

    hz = 100
    try:
        hz = int(os.sysconf("SC_CLK_TCK"))
    except Exception:
        hz = 100

    if hz <= 0:
        hz = 100

    return (uticks / float(hz), sticks / float(hz))


def _loadavg() -> tuple[float, float, float]:
    txt = _read_text("/proc/loadavg").strip()
    parts = txt.split()
    if len(parts) < 3:
        return (0.0, 0.0, 0.0)
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _mem_bytes() -> tuple[int, int]:
    txt = _read_text("/proc/meminfo")
    total_kb = 0
    avail_kb = 0
    for line in txt.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = _parse_kb_line(line)
        elif line.startswith("MemAvailable:"):
            avail_kb = _parse_kb_line(line)
    return (total_kb * 1024, avail_kb * 1024)


def _parse_kb_line(line: str) -> int:
    parts = line.split()
    if len(parts) < 2:
        return 0
    try:
        return int(parts[1])
    except Exception:
        return 0


def _net_bytes_total() -> tuple[int, int]:
    txt = _read_text("/proc/net/dev")
    rx_total = 0
    tx_total = 0
    for line in txt.splitlines():
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        iface = name.strip()
        if not iface or iface == "lo":
            continue
        cols = rest.split()
        if len(cols) < 16:
            continue
        try:
            rx_total += int(cols[0])
            tx_total += int(cols[8])
        except Exception:
            continue
    return (rx_total, tx_total)
