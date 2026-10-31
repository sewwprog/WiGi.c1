"""Network helper utilities for detecting host IP and available TCP ports."""

from __future__ import annotations

import socket


def get_lan_ip() -> str:
    """Return the primary local network IP of the current machine (laptop/server)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Does not actually send packets; asks OS routing table for outbound interface IP
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
    # Fallback: ask OS for any ephemeral free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])
