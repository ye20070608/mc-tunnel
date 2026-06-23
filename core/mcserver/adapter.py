"""Minecraft server adapter — wraps PaperMC lifecycle and RCON."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config.loader import Config
from core.audit.logger import AuditLogger
from core.mcserver.properties import ServerPropertiesGenerator
from core.mcserver.status import MCStatusCollector
from core.mcserver.whitelist import WhitelistManager
from core.procman.manager import ProcessManager


class MCServerAdapter:
    """Minecraft server adapter.

    Manages the PaperMC server subprocess, provides RCON-based command
    execution, and aggregates server status from both Server List Ping
    and RCON.

    Args:
        config: Application configuration (``config.mc`` is used).
        logger: Loguru logger bound with a module name.
    """

    def __init__(self, config: Config, logger) -> None:
        self._config = config
        self._log = logger

        # Build the Java command line
        jvm_parts = config.mc.jvm_args.split()
        paper_jar = self._find_jar()
        mc_cmd = [
            config.mc.java_path,
            "-Dfile.encoding=UTF-8",        # Force UTF-8 for file I/O (log4j, etc.)
            "-Dsun.stdout.encoding=UTF-8",  # Force UTF-8 for console output (JDK <18)
            "-Dsun.stderr.encoding=UTF-8",
            *jvm_parts,
            "-jar", paper_jar, "nogui",
        ]

        # Player tracking — updated from console output
        self._player_join_times: dict[str, "datetime"] = {}
        self._enriched_cache: dict[str, dict] = {}
        self._last_enrich: dict[str, float] = {}

        self._process = ProcessManager(
            name="paper-mc",
            cmd=mc_cmd,
            logger=logger,
            auto_restart=config.mc.auto_restart,
            restart_max=config.mc.restart_max_retries,
            stdout_callback=self._on_server_output,
        )

        # RCON settings: prefer server.properties, fall back to defaults
        self._rcon_host = "127.0.0.1"
        self._rcon_port = 25575
        self._rcon_password = ""
        self._load_rcon_config()

        self._status_collector = MCStatusCollector(
            host=self._rcon_host,
            port=config.mc.port,
            rcon_password=self._rcon_password,
            rcon_port=self._rcon_port,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the Minecraft server.

        Generates ``server.properties`` (with RCON enabled) before
        launching, then validates the EULA and the server jar.

        Returns:
            True if the server started successfully.
        """
        if not self._check_eula():
            return False

        # Generate server.properties before first launch
        props_path = Path("server.properties")
        if not props_path.exists():
            self._log.info("Generating server.properties...")
            generator = ServerPropertiesGenerator(self._config)
            self._rcon_password = generator.write(
                path=props_path,
                rcon_port=self._rcon_port,
                server_port=self._config.mc.port,
            )
            self._log.info(
                "server.properties created (RCON port={}, password={})",
                self._rcon_port,
                self._rcon_password[:4] + "****",
            )
            # Update the status collector with the new RCON password
            self._status_collector._rcon_password = self._rcon_password

        return self._process.start()

    def stop(self) -> bool:
        """Stop the Minecraft server.

        Attempts a graceful shutdown via RCON ``/stop`` first.  Falls
        back to killing the subprocess if RCON is unavailable or the
        server does not stop within a reasonable time.

        Returns:
            True if the server was stopped (or was not running).
        """
        if not self._process.is_running():
            return True

        # Try graceful shutdown via RCON
        try:
            self._rcon_command("say Server is shutting down...")
            self._rcon_command("stop")
            # Wait briefly for a graceful shutdown
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if not self._process.is_running():
                    return True
                time.sleep(0.5)
        except Exception:
            pass

        return self._process.stop(timeout=10.0)

    def restart(self) -> bool:
        """Restart the Minecraft server.

        Returns:
            True if the restart was successful.
        """
        self._log.info("Restarting Minecraft server...")
        return self._process.restart()

    def is_running(self) -> bool:
        """Check whether the Minecraft server process is alive.

        Returns:
            True if the subprocess is running.
        """
        return self._process.is_running()

    def send_command(self, cmd: str) -> str:
        """Send an RCON command and return the response.

        Args:
            cmd: The command string (e.g. ``"list"``, ``"whitelist add bob"``).

        Returns:
            The command response text.

        Raises:
            RuntimeError: If the RCON connection or command fails.
        """
        return self._rcon_command(cmd)

    def get_status(self) -> dict[str, Any]:
        """Return a comprehensive status dictionary.

        Combines Server List Ping data with RCON-augmented detail when
        available.  Returns a safe "offline" state when the server is not
        running.

        Returns:
            Dict with keys ``online``, ``onlinePlayers``, ``maxPlayers``,
            ``tps``, ``version``, ``motd``, ``uptime``, ``memory``, ``cpu``.
        """
        if not self._process.is_running():
            return {
                "online": False,
                "status": "stopped",
                "onlinePlayers": 0,
                "maxPlayers": 0,
                "tps": 0.0,
                "version": "",
                "motd": "",
                "uptime": 0.0,
                "memory": {},
                "cpu": 0.0,
            }

        result: dict[str, Any] = {"online": True, "status": "running"}

        # Basic info via Server List Ping
        try:
            basic = self._status_collector.get_basic_status()
            result.update(basic)
        except Exception as e:
            self._log.warning("Server List Ping failed: {}", e)
            result.update({"onlinePlayers": 0, "maxPlayers": 0, "motd": "", "version": ""})

        # Augment with RCON detail
        try:
            detailed = self._status_collector.get_detailed_status()
            result.update(detailed)
        except Exception as e:
            self._log.warning("RCON detail query failed: {}", e)
            result.update({"tps": 0.0, "uptime": 0.0, "memory": {}, "cpu": 0.0})

        return result

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

    def get_players(self) -> list[dict[str, Any]]:
        """Return a list of currently online players with enriched detail.

        Uses the RCON ``list`` command for basic names, then merges
        cached enrichment data (world, coordinates) and join-time
        tracking from console output.

        Returns:
            List of player dicts with keys ``name``, ``ping``,
            ``gamemode``, ``joined``, ``is_op``, ``online_time``,
            ``world``, ``coords``.
        """
        if not self._process.is_running():
            return []

        try:
            response = self._rcon_command("list")
            players = self._parse_player_list(response)
            ops = self._get_ops()
            now = datetime.now()

            for p in players:
                name = p["name"]
                p["is_op"] = name.lower() in ops

                # Online time from console join tracking
                join_time = self._player_join_times.get(name)
                if join_time:
                    p["online_time"] = self._format_duration(
                        (now - join_time).total_seconds()
                    )
                else:
                    p["online_time"] = ""

                # Enrichment cache (world + coords via RCON, lazy)
                enriched = self._enriched_cache.get(name, {})
                p["world"] = enriched.get("world", "")
                p["coords"] = enriched.get("coords", "")

                # Schedule enrichment if stale (>30 s) or never done
                last = self._last_enrich.get(name, 0)
                if (now.timestamp() - last) > 30:
                    import threading
                    threading.Thread(
                        target=self._enrich_player, args=(name,), daemon=True
                    ).start()

            return players
        except Exception as e:
            self._log.warning("Failed to get player list: {}", e)
            return []

    def _on_server_output(self, line: str) -> None:
        """Detect player join/leave events from server console output."""
        import re
        # "Archetto joined the game"
        m = re.search(r"(\w{2,16}) joined the game", line)
        if m:
            name = m.group(1)
            self._player_join_times[name] = datetime.now()
            # Eagerly enrich on join
            import threading
            threading.Thread(
                target=self._enrich_player, args=(name,), daemon=True
            ).start()
            return

        # "Archetto left the game"
        m = re.search(r"(\w{2,16}) left the game", line)
        if m:
            name = m.group(1)
            self._player_join_times.pop(name, None)
            self._enriched_cache.pop(name, None)
            self._last_enrich.pop(name, None)

    def _enrich_player(self, name: str) -> None:
        """Fetch world + coordinates for *name* via RCON and cache them."""
        import re
        try:
            now = time.time()
            self._last_enrich[name] = now

            # Get position
            pos_raw = self._rcon_command(f"data get entity {name} Pos")
            pos_match = re.search(r"\[([^\]]+)\]", pos_raw)
            if pos_match:
                parts = pos_match.group(1).replace("d", "").split(",")
                x, y, z = [float(v.strip()) for v in parts]
                coords = f"{x:.0f} / {y:.0f} / {z:.0f}"
            else:
                coords = ""

            # Get dimension
            dim_raw = self._rcon_command(f"data get entity {name} Dimension")
            dim_match = re.search(r'"([^"]+)"', dim_raw)
            if dim_match:
                dim_id = dim_match.group(1)
                dim_names = {
                    "minecraft:overworld": "主世界",
                    "minecraft:the_nether": "地狱",
                    "minecraft:the_end": "末地",
                }
                world = dim_names.get(dim_id, dim_id.replace("minecraft:", ""))
            else:
                world = "主世界"

            self._enriched_cache[name] = {"world": world, "coords": coords}
        except Exception as e:
            self._log.debug("Failed to enrich player '{}': {}", name, e)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds to a human-readable string."""
        if seconds < 0:
            return ""
        s = int(seconds)
        if s < 60:
            return f"{s}秒"
        if s < 3600:
            return f"{s // 60}分{s % 60}秒"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}时{m}分"

    def _get_ops(self) -> set[str]:
        """Return the set of operator player names from ``ops.json``.

        Returns:
            A set of lowercased player names, or an empty set if the
            file does not exist or cannot be parsed.
        """
        import json
        ops_path = Path("ops.json")
        if not ops_path.exists():
            return set()
        try:
            data = json.loads(ops_path.read_text(encoding="utf-8"))
            return {
                entry["name"].lower()
                for entry in data
                if isinstance(entry, dict) and "name" in entry
            }
        except Exception:
            return set()

    def kick_player(self, name: str, reason: str = "") -> bool:
        """Kick a player from the server by name.

        Args:
            name: The player name to kick.
            reason: Optional kick reason (shown in the disconnect screen).

        Returns:
            True if the command was sent successfully.
        """
        if not name or not name.strip():
            return False

        try:
            cmd = f"kick {name.strip()}"
            if reason:
                cmd += f" {reason}"
            self._rcon_command(cmd)
            return True
        except Exception as e:
            self._log.warning("Failed to kick player '{}': {}", name, e)
            return False

    # ------------------------------------------------------------------
    # Whitelist management
    # ------------------------------------------------------------------

    def get_whitelist(self) -> list[str]:
        """Return a list of whitelisted player names.

        Delegates to :class:`WhitelistManager`.

        Returns:
            List of player names (may be empty).
        """
        return WhitelistManager(self).list()

    def whitelist_add(self, name: str) -> bool:
        """Add a player to the whitelist.

        Delegates to :class:`WhitelistManager`.

        Args:
            name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not name or not name.strip():
            return False
        return WhitelistManager(self).add(name)

    def op_player(self, name: str) -> bool:
        """Make a player a server operator (OP) via RCON.

        Args:
            name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not name or not name.strip():
            return False

        try:
            self._rcon_command(f"op {name.strip()}")
            return True
        except Exception as e:
            self._log.warning("Failed to op player '{}': {}", name, e)
            return False

    def deop_player(self, name: str) -> bool:
        """Remove operator status from a player.

        Args:
            name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not name or not name.strip():
            return False

        try:
            self._rcon_command(f"deop {name.strip()}")
            return True
        except Exception as e:
            self._log.warning("Failed to deop player '{}': {}", name, e)
            return False

    def whitelist_remove(self, name: str) -> bool:
        """Remove a player from the whitelist.

        Delegates to :class:`WhitelistManager`.

        Args:
            name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not name or not name.strip():
            return False
        return WhitelistManager(self).remove(name)

    # ------------------------------------------------------------------
    # Log retrieval
    # ------------------------------------------------------------------

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent audit log entries.

        Delegates to :class:`AuditLogger` with the default log path
        ``logs/audit.log``.

        Args:
            limit: Maximum number of entries to return (newest first).

        Returns:
            A list of audit entry dicts.
        """
        try:
            audit = AuditLogger()
            return audit.get_logs(limit=limit)
        except Exception as e:
            self._log.warning("Failed to retrieve audit logs: {}", e)
            return []

    # ------------------------------------------------------------------
    # Version & world management
    # ------------------------------------------------------------------

    def get_installed_versions(self) -> list[dict]:
        """Return a list of installed PaperMC JAR versions.

        Scans the working directory for ``paper-*.jar`` files and
        extracts version and build numbers.

        Returns:
            List of dicts with ``version``, ``build``, ``file_name``,
            ``size_mb``, ``active``.
        """
        from pathlib import Path

        jars: list[dict] = []
        for jar_path in sorted(Path.cwd().glob("paper-*.jar"), reverse=True):
            name = jar_path.name
            # Parse: paper-{version}-{build}.jar
            stem = name.replace(".jar", "")
            parts = stem.split("-")
            version = parts[1] if len(parts) > 1 else "unknown"
            build = parts[2] if len(parts) > 2 else "0"
            size_mb = round(jar_path.stat().st_size / (1024 * 1024), 1)
            active = self._config.mc.version == version
            jars.append({
                "version": version,
                "build": build,
                "file_name": name,
                "size_mb": size_mb,
                "active": active,
            })
        return jars

    def switch_version(self, version: str) -> bool:
        """Switch the active PaperMC version.

        Updates the config and rebuilds the process command for the
        new JAR.  Requires a server restart to take effect.

        Args:
            version: Target PaperMC version string (e.g. "1.20.6").

        Returns:
            True if a JAR for *version* was found and the switch
            was prepared.
        """
        from pathlib import Path
        from config.loader import ConfigManager

        # Check that the version JAR exists
        matches = list(Path.cwd().glob(f"paper-{version}-*.jar"))
        if not matches:
            return False

        # Update in-memory config
        self._config.mc.version = version

        # Persist to YAML
        try:
            cm = ConfigManager("config/config.yaml")
            with open(cm.config_path, "r", encoding="utf-8") as fh:
                import yaml
                raw: dict = yaml.safe_load(fh) or {}
            raw.setdefault("mc", {})["version"] = version
            raw.setdefault("mc", {})["server_jar"] = str(matches[0])
            with open(cm.config_path, "w", encoding="utf-8") as fh:
                yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception:
            pass

        self._log.info("Switched active version to {}", version)
        return True

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    def get_console_output(self, limit: int = 100) -> list[str]:
        """Return recent lines of the Minecraft server console output.

        Retrieves lines from the process manager's ring buffer.

        Args:
            limit: Maximum number of lines to return (newest first).

        Returns:
            List of console output lines (may be empty if the server
            has not been started).
        """
        return self._process.get_console_buffer(limit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_player_list(response: str) -> list[dict[str, Any]]:
        """Parse the response of the MC server ``/list`` command.

        Expected format::

            There are 3 of a max of 20 players online: Steve, Alex, Bob

        Args:
            response: Raw RCON response text.

        Returns:
            List of player dicts with keys ``name``, ``ping``,
            ``gamemode``, ``joined``.
        """
        match = re.search(r"players online:?\s*(.*)", response)
        if not match:
            return []

        names_str = match.group(1).strip()
        if not names_str:
            return []

        names = [n.strip() for n in names_str.split(",") if n.strip()]
        return [
            {
                "name": name,
                "ping": 0,
                "gamemode": "",
                "joined": "",
            }
            for name in names
        ]

    def _check_eula(self) -> bool:
        """Check whether the Minecraft EULA has been accepted.

        Returns:
            True if ``eula.txt`` exists and contains ``eula=true``.
        """
        eula_path = Path("eula.txt")
        if not eula_path.exists():
            self._log.error(
                "eula.txt not found. Please read and accept the Minecraft EULA, "
                "then set 'eula=true' in eula.txt"
            )
            return False

        content = eula_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("eula="):
                accepted = stripped.split("=", 1)[1].strip().lower() == "true"
                if not accepted:
                    self._log.error(
                        "EULA not accepted. Set 'eula=true' in eula.txt"
                    )
                return accepted

        self._log.error("Could not find 'eula=' line in eula.txt")
        return False

    def _find_jar(self) -> str:
        """Locate the Minecraft server JAR file in the working directory.

        Searches for ``paper-*.jar``, ``minecraft_server*.jar``, and
        ``server.jar`` in order.

        Returns:
            Path to the first matching JAR, or ``"paper.jar"`` as fallback.
        """
        server_dir = Path.cwd()
        for pattern in ("paper-*.jar", "minecraft_server*.jar", "server.jar"):
            matches = list(server_dir.glob(pattern))
            if matches:
                jar_path = str(matches[0])
                self._log.info("Found server jar: {}", jar_path)
                return jar_path

        fallback = "paper.jar"
        self._log.warning("No server jar found, defaulting to '{}'", fallback)
        return fallback

    def _load_rcon_config(self) -> None:
        """Read RCON settings from ``server.properties``, if available."""
        props_path = Path("server.properties")
        if not props_path.exists():
            self._log.debug("server.properties not found, using default RCON settings")
            return

        props: dict[str, str] = {}
        for line in props_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()

        if props.get("enable-rcon", "false").lower() == "true":
            try:
                self._rcon_port = int(props.get("rcon.port", 25575))
            except (ValueError, TypeError):
                pass
            self._rcon_password = props.get("rcon.password", "")
            self._log.debug(
                "RCON configured (port={})", self._rcon_port
            )

    def _rcon_command(self, cmd: str) -> str:
        """Execute an RCON command and return the response.

        Args:
            cmd: Command string to send.

        Returns:
            Response text.

        Raises:
            RuntimeError: If the connection or command fails.
        """
        try:
            from mcipc.rcon import Client

            with Client(self._rcon_host, self._rcon_port) as client:
                client.login(self._rcon_password)
                response = client.run(cmd)
                return str(response or "")
        except ImportError:
            raise RuntimeError("mcipc library is not installed (pip install mcipc)")
        except Exception as e:
            raise RuntimeError(f"RCON command '{cmd}' failed: {e}") from e
