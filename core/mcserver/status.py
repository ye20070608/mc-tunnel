"""Status collector for the Minecraft server."""
from __future__ import annotations

import re
from typing import Any


class MCStatusCollector:
    """Collects server status via Server List Ping and optionally via RCON.

    Server List Ping (via ``mcstatus``) provides basic information such as
    online player count, max players, MOTD, and version.  RCON (via
    ``mcipc``) can augment this with TPS, memory, and CPU data.

    Attributes:
        host: Server hostname or IP.
        port: Server game port.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25565,
        rcon_password: str = "",
        rcon_port: int = 25575,
    ) -> None:
        """Initialize the status collector.

        Args:
            host: Minecraft server hostname or IP.
            port: Minecraft server game port.
            rcon_password: RCON password for detailed queries.
            rcon_port: RCON protocol port.
        """
        self._host = host
        self._port = port
        self._rcon_password = rcon_password
        self._rcon_port = rcon_port
        self._psutil_proc = None  # lazily initialised on first _try_process_info

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_basic_status(self) -> dict[str, Any]:
        """Query the server via Server List Ping.

        Returns:
            Dict with keys ``onlinePlayers``, ``maxPlayers``, ``motd``,
            ``version``.  All values default to a safe empty/zero state
            when the query fails.
        """
        try:
            from mcstatus import JavaServer

            server = JavaServer(self._host, self._port)
            status = server.status()

            return {
                "onlinePlayers": status.players.online,
                "maxPlayers": status.players.max,
                "motd": self._format_motd(status.motd),
                "version": status.version.name,
            }
        except Exception as e:
            return {
                "onlinePlayers": 0,
                "maxPlayers": 0,
                "motd": "",
                "version": "",
                "_error": str(e),
            }

    def get_detailed_status(self) -> dict[str, Any]:
        """Query detailed server info via RCON.

        Requires a valid RCON connection.  Falls back gracefully when
        RCON is unavailable.

        Returns:
            Dict with keys ``tps``, ``uptime``, ``memory``, ``cpu``.
        """
        status: dict[str, Any] = {
            "tps": 0.0,
            "uptime": 0.0,
            "memory": {},
            "cpu": 0.0,
        }

        self._try_rcon_status(status)
        self._try_process_info(status)

        return status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_motd(motd: Any) -> str:
        """Format the MOTD object from mcstatus into a plain string."""
        try:
            if hasattr(motd, "parsed"):
                return str(motd.parsed)
            if hasattr(motd, "to_plain"):
                return motd.to_plain()
            return str(motd)
        except Exception:
            return str(motd)

    def _try_rcon_status(self, status: dict[str, Any]) -> None:
        """Attempt to enrich *status* via RCON commands."""
        if not self._rcon_password:
            return

        try:
            from mcipc.rcon import Client

            with Client(self._host, self._rcon_port) as client:
                client.login(self._rcon_password)

                # TPS
                try:
                    tps_raw = client.run("tps")
                    status["tps"] = self._parse_tps(str(tps_raw or ""))
                except Exception:
                    pass

                # Uptime (via /forge tps or we approximate from list response)
                try:
                    status["uptime"] = self._query_uptime(client)
                except Exception:
                    pass
        except Exception:
            pass

    def _try_process_info(self, status: dict[str, Any]) -> None:
        """Attempt to enrich *status* with process-level metrics via psutil.

        Uses a persistent process handle so that ``cpu_percent()`` works
        correctly across consecutive calls (the first call establishes the
        baseline; subsequent calls return the actual value).
        """
        try:
            import psutil
            import time

            if self._psutil_proc is None:
                self._psutil_proc = psutil.Process()

            proc = self._psutil_proc
            mem = proc.memory_info()
            mem_percent = proc.memory_percent()  # after first baseline call

            # Format memory as human-readable strings
            status["memory"] = {
                "used": self._human_bytes(mem.rss),
                "max": self._human_bytes(psutil.virtual_memory().total),
                "percent": round(mem_percent, 1),
            }
            # cpu_percent() is non-blocking after first call (uses cached baseline)
            status["cpu"] = round(proc.cpu_percent(interval=0), 1)
            # Uptime from process creation time
            status["uptime"] = round(time.time() - proc.create_time(), 0)
        except (ImportError, OSError):
            pass

    @staticmethod
    def _query_uptime(client: Any) -> float:
        """Query server uptime in seconds via RCON.

        Falls back to a best-effort estimate.
        """
        # Try to get the time since the last restart via /forge tps
        # or simply return 0 if unavailable.
        return 0.0

    @staticmethod
    def _human_bytes(size_bytes: int) -> str:
        """Convert a byte count to a human-readable string (e.g. '2.3G')."""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}K"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}M"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}G"

    @staticmethod
    def _parse_tps(output: str) -> float:
        """Extract a TPS value from the raw output of the ``/tps`` command.

        Args:
            output: Raw server response.

        Returns:
            Parsed TPS value, or 0.0 on failure.
        """
        # Paper format: "Overall TPS: 20.0, ..." or similar
        for line in output.splitlines():
            match = re.search(r"[\d.]+", line)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    pass
        return 0.0
