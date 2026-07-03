"""Minecraft server adapter — wraps PaperMC lifecycle and RCON."""
from __future__ import annotations

import os
import re
import threading
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

        # Pending players — players rejected by whitelist
        self._pending_players: dict[str, dict] = {}   # name → {time, ip}
        # IP tracking — last known IP per player (from join events)
        self._player_ips: dict[str, str] = {}          # name → ip

        self._process = ProcessManager(
            name="paper-mc",
            cmd=mc_cmd,
            logger=logger,
            auto_restart=config.mc.auto_restart,
            restart_max=config.mc.restart_max_retries,
            stdout_callback=self._on_server_output,
            cwd=Path.cwd() / "server",
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

        # Background cache — avoids blocking frontend request threads on RCON.
        # A daemon thread polls the MC server periodically and stores frozen
        # snapshots; API handlers read from the cache with zero latency.
        self._cache_lock = threading.Lock()
        self._cache_status: dict[str, Any] = {
            "online": False, "status": "stopped", "onlinePlayers": 0,
            "maxPlayers": 0, "tps": 0.0, "version": "", "motd": "",
            "uptime": 0.0, "memory": {}, "cpu": 0.0,
        }
        self._cache_players: list[dict[str, Any]] = []
        self._cache_console: list[str] = []
        self._cache_thread: threading.Thread | None = None
        self._cache_running = False

        # Start background cache immediately so API handlers never block
        self._start_cache_thread()

    # ------------------------------------------------------------------
    # Background cache — polls MC server so API handlers never block
    # ------------------------------------------------------------------

    def _start_cache_thread(self) -> None:
        """Launch the background cache poller (daemon, restarts on crash)."""
        if self._cache_running:
            return
        self._cache_running = True
        self._cache_thread = threading.Thread(
            target=self._cache_poller, daemon=True, name="mc-cache-poller"
        )
        self._cache_thread.start()
        self._log.info("Background status cache started")

    def _stop_cache_thread(self) -> None:
        """Signal the cache poller to stop."""
        self._cache_running = False

    def _cache_poller(self) -> None:
        """Background loop: poll MC server every 3 s, update cache."""
        while self._cache_running:
            try:
                self._refresh_cache()
            except Exception:
                pass  # keep last-known-good values
            time.sleep(3)

    def _refresh_cache(self) -> None:
        """Single poll cycle — refresh all cached data from the MC server."""
        running = self._process.is_running()
        now = time.time()

        # ── Status ──────────────────────────────────────────────
        status: dict[str, Any] = {"online": False, "status": "stopped",
                                   "onlinePlayers": 0, "maxPlayers": 0,
                                   "tps": 0.0, "version": "", "motd": "",
                                   "uptime": 0.0, "memory": {}, "cpu": 0.0}
        if running:
            status["online"] = True
            status["status"] = "running"
            try:
                basic = self._status_collector.get_basic_status()
                status.update(basic)
            except Exception:
                pass
            try:
                detailed = self._status_collector.get_detailed_status()
                status.update(detailed)
            except Exception:
                pass

        # ── Players ─────────────────────────────────────────────
        players: list[dict[str, Any]] = []
        if running:
            try:
                response = self._rcon_command("list")
                players = self._parse_player_list(response)
                ops = self._get_ops()
                for p in players:
                    name = p["name"]
                    p["is_op"] = name.lower() in ops
                    join_time = self._player_join_times.get(name)
                    if not join_time:
                        self._player_join_times[name] = datetime.now()
                        join_time = self._player_join_times[name]
                    elapsed = datetime.now() - join_time
                    p["online_time"] = str(elapsed).split(".")[0]
                    # Enrich with coords / world (throttled to every 5 s)
                    if name not in self._last_enrich or now - self._last_enrich[name] > 5:
                        self._enrich_player(name)
                        self._last_enrich[name] = now
                    cached = self._enriched_cache.get(name, {})
                    p["world"] = cached.get("world", "未知")
                    p["coords"] = cached.get("coords", "未知")
            except Exception:
                pass  # keep previous player list

        # ── Console ─────────────────────────────────────────────
        console: list[str] = []
        try:
            console = self._get_console_raw(limit=200)
        except Exception:
            pass

        # ── Commit ──────────────────────────────────────────────
        with self._cache_lock:
            self._cache_status = status
            self._cache_players = players
            self._cache_console = console

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the Minecraft server.

        Ensures ``server.properties`` has RCON enabled before launching.
        If the file exists, patches missing/invalid RCON settings in-place;
        otherwise generates a fresh copy from the config template.

        Returns:
            True if the server started successfully.
        """
        if not self._check_eula():
            return False

        # Ensure RCON is enabled in server.properties (always, not just on first run)
        props_path = Path("server/server.properties")
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
        else:
            # Existing server.properties — patch RCON settings if missing/broken
            self._rcon_password = self._ensure_rcon_enabled(props_path)
            self._log.info(
                "server.properties patched: RCON enabled (port={})",
                self._rcon_port,
            )

        # Update the status collector with the current RCON password
        self._status_collector._rcon_password = self._rcon_password
        self._status_collector._rcon_port = self._rcon_port

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

        # Tell the process manager that we're intentionally stopping the
        # server so the auto-restart monitor does not mistake the RCON
        # shutdown for an unexpected crash.
        self._process.request_stop()

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
        """Return cached server status (updated every 3 s by background thread).

        Never blocks — reads from the thread-safe cache.
        """
        with self._cache_lock:
            return dict(self._cache_status)

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

    def get_players(self) -> list[dict[str, Any]]:
        """Return cached online player list (updated every 3 s by background thread).

        Never blocks — reads from the thread-safe cache.
        """
        with self._cache_lock:
            return list(self._cache_players)

    def _on_server_output(self, line: str) -> None:
        """Detect player join/leave/rejection events from server console output."""
        import re
        now = datetime.now()

        # "Archetto joined the game"
        m = re.search(r"(\w{2,16}) joined the game", line)
        if m:
            name = m.group(1)
            self._player_join_times[name] = now
            # Clear from pending once they successfully join
            self._pending_players.pop(name, None)
            # Record last-online timestamp via WhitelistManager (proper locking)
            try:
                WhitelistManager(self).record_last_online(name, now)
            except Exception:
                pass
            # Eagerly enrich on join
            t = threading.Thread(target=self._enrich_player, args=(name,), daemon=True)
            t.start()
            return

        # "Archetto left the game"
        m = re.search(r"(\w{2,16}) left the game", line)
        if m:
            name = m.group(1)
            self._player_join_times.pop(name, None)
            self._enriched_cache.pop(name, None)
            self._last_enrich.pop(name, None)
            # Record last-online on leave for accurate time tracking
            try:
                WhitelistManager(self).record_last_online(name, now)
            except Exception:
                pass
            return

        # "Steve[/192.168.1.5:54321] logged in with entity id ..."
        m = re.search(r"(\w{2,16})\[/([\d.]+):\d+\] logged in", line)
        if m:
            name = m.group(1)
            ip = m.group(2)
            self._player_ips[name] = ip
            return

        # Whitelist rejection: "You are not whitelisted on this server!"
        if "not whitelisted" in line.lower() or "not whitelisted" in line:
            # Try to extract player name from GameProfile or fallback
            name_m = re.search(r"name=(\w{2,16})", line)
            ip_m = re.search(r"\(/([\d.]+):\d+\)", line)
            if name_m:
                pending_name = name_m.group(1)
                pending_ip = ip_m.group(1) if ip_m else ""
                self._pending_players[pending_name] = {
                    "time": now.strftime("%H:%M:%S"),
                    "ip": pending_ip,
                }

    def _enrich_player(self, name: str) -> None:
        """Fetch world, coordinates, and gamemode for *name* via RCON."""
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

            # Get gamemode (0=survival, 1=creative, 2=adventure, 3=spectator)
            gamemode = ""
            try:
                gm_raw = self._rcon_command(f"data get entity {name} playerGameType")
                gm_match = re.search(r"(\d+)", gm_raw)
                if gm_match:
                    gamemode = gm_match.group(1)
            except Exception:
                pass

            self._enriched_cache[name] = {"world": world, "coords": coords, "gamemode": gamemode}
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
        ops_path = Path("server/ops.json")
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
        """Return recent server log entries from PaperMC's ``logs/latest.log``.

        Parses lines in the standard MC server log format::

            [HH:MM:SS LEVEL]: message text

        Falls back to the in-memory console buffer if the log file does
        not exist or is empty.

        Args:
            limit: Maximum number of entries to return (newest first).

        Returns:
            A list of dicts with keys ``time``, ``level``, ``message``.
        """
        entries = self._read_server_log(limit)
        if entries:
            return entries

        # Fallback: parse in-memory console buffer lines
        raw_lines = self._process.get_console_buffer(limit)
        return self._parse_console_lines(raw_lines)

    def _read_server_log(self, limit: int) -> list[dict[str, Any]]:
        """Read and parse the PaperMC ``logs/latest.log`` file.

        Returns newest entries first, up to *limit*.
        """
        from pathlib import Path

        log_path = Path("server/logs/latest.log")
        if not log_path.is_file():
            return []

        try:
            raw = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        lines = raw.splitlines()
        entries = self._parse_console_lines(lines)
        entries.reverse()  # newest first
        return entries[:limit]

    @staticmethod
    def _parse_console_lines(lines: list[str]) -> list[dict[str, Any]]:
        """Parse raw console/log lines into structured entries.

        Handles the standard PaperMC format::

            [13:45:22 INFO]: message text

        as well as continuation lines (no timestamp prefix — appended
        to the previous entry's message).

        Args:
            lines: Raw text lines from the console or log file.

        Returns:
            List of dicts with ``time``, ``level``, ``message``, in the
            order they appear (oldest first).
        """
        import re

        # Pattern: [HH:MM:SS LEVEL]: rest of message
        _LOG_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\s+(\w+)\]:\s*(.*)")

        entries: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip("\r")
            if not line:
                continue
            m = _LOG_RE.match(line)
            if m:
                entries.append({
                    "time": m.group(1),
                    "level": m.group(2).upper(),
                    "message": m.group(3),
                })
            elif entries:
                # Continuation line (e.g. stack trace) — append to previous
                entries[-1]["message"] += "\n" + line

        return entries

    # ------------------------------------------------------------------
    # Version & world management
    # ------------------------------------------------------------------

    def get_installed_versions(self) -> list[dict]:
        """Return a list of installed PaperMC JAR versions.

        Scans ``server/versions/*/`` for ``paper-*.jar`` and ``mojang_*.jar``
        files and extracts version and build numbers.  Also scans the legacy
        flat ``server/`` layout for backward compatibility.

        Returns:
            List of dicts with ``version``, ``build``, ``file_name``,
            ``size_mb``, ``active``.
        """
        import re
        from pathlib import Path

        jars: list[dict] = []
        seen: dict[str, dict] = {}  # version → best entry (highest build)

        def _collect(jar_path: Path) -> None:
            name = jar_path.name
            size_mb = round(jar_path.stat().st_size / (1024 * 1024), 1)
            version = "unknown"
            build = 0
            build_str = "0"

            # paper-{version}-{build}.jar (e.g. paper-1.20.1-196.jar)
            if name.startswith("paper-"):
                stem = name.replace(".jar", "")
                parts = stem.split("-")
                version = parts[1] if len(parts) > 1 else "unknown"
                build_str = parts[2] if len(parts) > 2 else "0"
                try:
                    build = int(build_str)
                except ValueError:
                    build = 0
            # mojang_{version}.jar (e.g. mojang_1.20.1.jar)
            elif name.startswith("mojang_"):
                stem = name.replace(".jar", "")
                # mojang_1.20.1 → version=1.20.1
                version = stem.replace("mojang_", "")
                if version.startswith("_"):
                    version = version[1:]
                build_str = "0"

            if version not in seen or build > seen[version]["_build_num"]:
                seen[version] = {
                    "version": version,
                    "build": build_str,
                    "file_name": name,
                    "size_mb": size_mb,
                    "_build_num": build,
                }

        # Primary: version-isolated directories
        versions_root = Path.cwd().joinpath("server", "versions")
        if versions_root.exists():
            for jar_path in sorted(versions_root.glob("*/paper-*.jar"), reverse=True):
                _collect(jar_path)
            for jar_path in sorted(versions_root.glob("*/mojang_*.jar"), reverse=True):
                _collect(jar_path)

        # Legacy: flat server/ directory
        for jar_path in sorted(Path.cwd().joinpath("server").glob("paper-*.jar"), reverse=True):
            _collect(jar_path)
        for jar_path in sorted(Path.cwd().joinpath("server").glob("mojang_*.jar"), reverse=True):
            _collect(jar_path)

        for entry in seen.values():
            entry["active"] = self._config.mc.version == entry["version"]
            del entry["_build_num"]
            jars.append(entry)

        # Sort by version (newest first)
        jars.sort(key=lambda e: [int(x) for x in e["version"].split(".")], reverse=True)
        return jars

    @staticmethod
    def _validate_version(version: str) -> bool:
        """Validate a PaperMC version string before using in glob patterns.

        Only allows digits and dots (e.g. "1.20.4").  Rejects glob
        metacharacters (*, ?, [, ]) that could expand the search scope.
        """
        import re
        return bool(re.match(r"^[\d.]+$", version))

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

        # Validate version before using in glob (prevents glob injection)
        if not self._validate_version(version):
            self._log.warning("Invalid version string rejected: {}", version)
            return False

        # Check that the version JAR exists in the version-isolated directory
        version_dir = Path.cwd().joinpath("server", "versions", version)
        matches = list(version_dir.glob(f"paper-{version}-*.jar"))
        # 兼容无 build 号的文件名: paper-{version}.jar
        matches += list(version_dir.glob(f"paper-{version}.jar"))
        # Fallback: legacy flat layout
        if not matches:
            matches = list(Path.cwd().joinpath("server").glob(f"paper-{version}-*.jar"))
            matches += list(Path.cwd().joinpath("server").glob(f"paper-{version}.jar"))
        if not matches:
            return False

        jar_rel = os.path.relpath(str(matches[0]), str(Path.cwd()))
        # Update in-memory config
        self._config.mc.version = version
        self._config.mc.server_jar = jar_rel

        # Persist to YAML (原子写入，防止文件损坏)
        try:
            import tempfile
            cm = ConfigManager("config/config.yaml")
            with open(cm.config_path, "r", encoding="utf-8") as fh:
                import yaml
                raw: dict = yaml.safe_load(fh) or {}
            raw.setdefault("mc", {})["version"] = version
            raw.setdefault("mc", {})["server_jar"] = jar_rel

            config_dir = os.path.dirname(cm.config_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".yaml")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    yaml.dump(raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
                os.replace(tmp_path, cm.config_path)
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception:
            pass

        # Rebuild the process command to use the new JAR
        new_jar = str(matches[0])
        jvm_parts = self._config.mc.jvm_args.split()
        new_cmd = [
            self._config.mc.java_path,
            "-Dfile.encoding=UTF-8",
            "-Dsun.stdout.encoding=UTF-8",
            "-Dsun.stderr.encoding=UTF-8",
            *jvm_parts,
            "-jar", new_jar, "nogui",
        ]
        from core.procman.manager import ProcessManager as PM
        self._process = PM(
            name="paper-mc",
            cmd=new_cmd,
            logger=self._log,
            auto_restart=self._config.mc.auto_restart,
            restart_max=self._config.mc.restart_max_retries,
            stdout_callback=self._on_server_output,
            cwd=Path.cwd() / "server",
        )

        self._log.info("Switched active version to {}", version)
        return True

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    def get_pending_players(self) -> list[dict]:
        """Return recently rejected players (not on whitelist).

        Automatically filters out names that are now whitelisted.

        Returns:
            List of dicts with ``name``, ``time``, ``ip``.
        """
        # Filter out players who are now whitelisted
        whitelisted = set()
        try:
            from core.mcserver.whitelist import WhitelistManager
            wm = WhitelistManager(self)
            for entry in wm.list():
                whitelisted.add(entry.get("name", "").lower())
        except Exception:
            pass

        result = []
        for name, info in self._pending_players.items():
            if name.lower() not in whitelisted:
                result.append({
                    "name": name,
                    "time": info.get("time", ""),
                    "ip": info.get("ip", ""),
                })
        # Newest first
        result.reverse()
        return result

    def get_player_ips(self) -> dict[str, str]:
        """Return the last known IP for each player.

        Returns:
            Dict mapping player name → IP address string.
        """
        return dict(self._player_ips)

    def get_console_output(self, limit: int = 100) -> list[str]:
        """Return cached console lines (updated every 3 s by background thread).

        Never blocks — reads from the thread-safe cache.
        """
        with self._cache_lock:
            lines = list(self._cache_console)
        return lines[-limit:] if limit > 0 else lines

    def _get_console_raw(self, limit: int = 200) -> list[str]:
        """Read console buffer directly (used by cache refresher, may block)."""
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
        eula_path = Path("server/eula.txt")
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

        Priority:
        1. ``mc.server_jar`` from config (explicit path)
        2. ``server/versions/{version}/paper-{version}-*.jar`` matching configured version
        3. ``server/versions/*/paper-*.jar`` (any installed version, newest first)
        4. Legacy fallback: ``server/paper-*.jar``, ``server/server.jar``
        5. ``"paper.jar"`` as last-resort fallback

        Returns:
            Path to the best matching JAR.
        """
        server_dir = Path.cwd() / "server"

        # 1) Explicit path from config
        explicit = self._config.mc.server_jar
        if explicit and Path(explicit).exists():
            explicit_abs = str(Path(explicit).resolve())
            self._log.info("Using explicit server jar: {}", explicit_abs)
            return explicit_abs

        # 2) Match configured version — server/versions/{version}/
        ver = self._config.mc.version
        if ver:
            version_dir = server_dir / "versions" / ver
            matches = sorted(version_dir.glob(f"paper-{ver}-*.jar"), reverse=True)
            # 兼容无 build 号的文件名: paper-{version}.jar
            matches_no_build = sorted(version_dir.glob(f"paper-{ver}.jar"), reverse=True)
            matches = matches + matches_no_build
            if matches:
                self._log.info("Found version-matched server jar: {}", matches[0].name)
                return str(matches[0])

        # 3) Fallback: any installed version — server/versions/*/
        versions_root = server_dir / "versions"
        if versions_root.exists():
            matches = sorted(versions_root.glob("*/paper-*.jar"), reverse=True)
            if matches:
                jar_path = str(matches[0])
                self._log.info("Found server jar in versions/: {}", jar_path)
                return jar_path

        # 4) Legacy fallback: flat server/ directory (pre-migration)
        for pattern in ("paper-*.jar", "minecraft_server*.jar", "server.jar"):
            matches = sorted(server_dir.glob(pattern), reverse=True)
            if matches:
                jar_path = str(matches[0])
                self._log.info("Found server jar (legacy): {}", jar_path)
                return jar_path

        fallback = "paper.jar"
        self._log.warning("No server jar found, defaulting to '{}'", fallback)
        return fallback

    def _load_rcon_config(self) -> None:
        """Read RCON settings from ``server.properties``, if available."""
        props_path = Path("server/server.properties")
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

    def _ensure_rcon_enabled(self, props_path: Path) -> str:
        """Patch an existing server.properties to ensure RCON is enabled.

        Returns the RCON password (existing or newly generated).
        """
        import secrets
        import string
        import os

        lines = props_path.read_text(encoding="utf-8").splitlines()
        props: dict[str, str] = {}
        line_indices: dict[str, int] = {}
        for i, line in enumerate(lines):
            line_s = line.strip()
            if not line_s or line_s.startswith("#") or "=" not in line_s:
                continue
            key, _, value = line_s.partition("=")
            key = key.strip()
            props[key] = value.strip()
            line_indices[key] = i

        changed = False

        # Ensure enable-rcon=true
        if props.get("enable-rcon", "false").lower() != "true":
            if "enable-rcon" in line_indices:
                lines[line_indices["enable-rcon"]] = "enable-rcon=true"
            else:
                lines.append("enable-rcon=true")
            changed = True

        # Ensure rcon.port is set
        rcon_port_str = str(self._rcon_port)
        if props.get("rcon.port", "") != rcon_port_str:
            if "rcon.port" in line_indices:
                lines[line_indices["rcon.port"]] = f"rcon.port={rcon_port_str}"
            else:
                lines.append(f"rcon.port={rcon_port_str}")
            changed = True

        # Ensure rcon.password is set (non-empty)
        password = props.get("rcon.password", "")
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = "".join(secrets.choice(alphabet) for _ in range(16))
            if "rcon.password" in line_indices:
                lines[line_indices["rcon.password"]] = f"rcon.password={password}"
            else:
                lines.append(f"rcon.password={password}")
            changed = True
            self._log.info("Generated new RCON password")

        if changed:
            # Atomic write via temp file
            tmp_path = Path(str(props_path) + ".tmp")
            tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(str(tmp_path), str(props_path))
            self._log.info("server.properties updated: RCON settings patched")

        # Re-read RCON config from the patched file
        self._load_rcon_config()
        return self._rcon_password

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

            with Client(self._rcon_host, self._rcon_port, timeout=3.0) as client:
                client.login(self._rcon_password)
                response = client.run(cmd)
                return str(response or "")
        except ImportError:
            raise RuntimeError("mcipc library is not installed (pip install mcipc)")
        except Exception as e:
            raise RuntimeError(f"RCON command '{cmd}' failed: {e}") from e
