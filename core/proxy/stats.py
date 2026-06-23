"""Thread-safe connection and traffic statistics for the TCP proxy.

All public methods are safe to call from multiple threads simultaneously.
"""

from __future__ import annotations

import threading
from typing import Dict


class ProxyStats:
    """Aggregate connection and byte-count statistics.

    Tracks active/total connections grouped by protocol (MC, HTTP, unknown)
    as well as transferred bytes in both directions.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections_total: int = 0
        self._connections_active: int = 0
        self._mc_connections: int = 0
        self._http_blocked: int = 0
        self._unknown_blocked: int = 0
        self._bytes_in: int = 0
        self._bytes_out: int = 0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_connection(self, proto: str) -> None:
        """Record one new connection of the given protocol type.

        Args:
            proto: ``'mc'``, ``'http'``, or ``'unknown'``.
        """
        with self._lock:
            self._connections_total += 1
            self._connections_active += 1
            if proto == "mc":
                self._mc_connections += 1
            elif proto == "http":
                self._http_blocked += 1
            else:
                self._unknown_blocked += 1

    def record_disconnection(self) -> None:
        """Decrement the active connection count."""
        with self._lock:
            if self._connections_active > 0:
                self._connections_active -= 1

    def record_bytes(self, incoming: int, outgoing: int) -> None:
        """Record transferred bytes.

        Args:
            incoming: Bytes received from the remote.
            outgoing: Bytes sent to the remote.
        """
        with self._lock:
            self._bytes_in += incoming
            self._bytes_out += outgoing

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Return an atomic snapshot of all counters.

        Returns:
            A dict with keys ``connections_total``, ``connections_active``,
            ``mc_connections``, ``http_blocked``, ``unknown_blocked``,
            ``bytes_in``, ``bytes_out``.
        """
        with self._lock:
            return {
                "connections_total": self._connections_total,
                "connections_active": self._connections_active,
                "mc_connections": self._mc_connections,
                "http_blocked": self._http_blocked,
                "unknown_blocked": self._unknown_blocked,
                "bytes_in": self._bytes_in,
                "bytes_out": self._bytes_out,
            }
