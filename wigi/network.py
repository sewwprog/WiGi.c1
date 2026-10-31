"""Network helper utilities and host system metrics."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import socket
import sys
from typing import Any


def get_lan_ip() -> str:
    """Return the primary local network IP of the current machine (laptop/server)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass

    return "127.0.0.1"


def is_wsl() -> bool:
    """Detect whether Python is running inside Ubuntu/Linux on Windows (WSL)."""
    try:
        proc_ver = Path("/proc/version")
        if proc_ver.exists():
            text = proc_ver.read_text(encoding="utf-8", errors="ignore").lower()
            return "microsoft" in text or "wsl" in text
    except OSError:
        pass
    return False


def is_port_free(port: int, host: str = "0.0.0.0") -> bool:
    """Check whether TCP `port` can be bound on `host`."""
    if not (1 <= port <= 65535):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(start_port: int = 8000, max_tries: int = 100) -> int:
    """Find the first available port starting at `start_port`."""
    for port in range(start_port, min(start_port + max_tries, 65536)):
        if is_port_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])


def _read_memory_mb() -> dict[str, int | float] | None:
    """Read RAM usage in MB (Linux/WSL via /proc/meminfo)."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    try:
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.strip().split()
            if parts and parts[0].isdigit():
                values[key.strip()] = int(parts[0])  # kB
        total_kb = values.get("MemTotal", 0)
        avail_kb = values.get("MemAvailable", values.get("MemFree", 0))
        if total_kb <= 0:
            return None
        used_kb = max(0, total_kb - avail_kb)
        total_mb = round(total_kb / 1024)
        used_mb = round(used_kb / 1024)
        avail_mb = round(avail_kb / 1024)
        percent = round((used_kb / total_kb) * 100, 1)
        return {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "available_mb": avail_mb,
            "percent": percent,
        }
    except OSError:
        return None


def get_system_metrics(workspace_dir: Path) -> dict[str, Any]:
    """Collect CPU, RAM, disk, and OS details for the server dashboard."""
    disk_info: dict[str, Any] | None = None
    try:
        target = workspace_dir if workspace_dir.exists() else Path.cwd()
        usage = shutil.disk_usage(target)
        total_gb = round(usage.total / (1024**3), 2)
        used_gb = round(usage.used / (1024**3), 2)
        free_gb = round(usage.free / (1024**3), 2)
        pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
        disk_info = {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "percent": pct,
        }
    except OSError:
        pass

    load_avg: list[float] | None = None
    getloadavg = getattr(os, "getloadavg", None)
    if callable(getloadavg):
        try:
            l1, l5, l15 = getloadavg()
            load_avg = [round(l1, 2), round(l5, 2), round(l15, 2)]
        except OSError:
            pass

    os_label = f"{platform.system()} {platform.release()}"
    if is_wsl():
        os_label += " (WSL / Ubuntu)"

    return {
        "os": os_label,
        "python": sys.version.split()[0],
        "cpu_cores": os.cpu_count() or 1,
        "load_avg": load_avg,
        "memory": _read_memory_mb(),
        "disk": disk_info,
        "is_wsl": is_wsl(),
    }
