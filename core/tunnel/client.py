"""frp client (frpc) subprocess lifecycle management.

Starts, monitors, and stops the frpc binary.  Tracks connection
state (disconnected → connecting → connected → error) by parsing
frpc stdout output.
"""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import loguru

from config.loader import Config
from core.tunnel.config import FrpConfigGenerator


class FrpClient:
    """Manages the frp client (frpc) subprocess.

    Usage::

        client = FrpClient(config)
        client.start()
        ...
        status = client.get_status()
        client.stop()
    """

    CONFIG_PATH: str = "frp/frpc.ini"

    def __init__(
        self,
        config: Config,
        logger=None,
        frp_binary: str = "frpc",
    ) -> None:
        """Initialise the frp client manager.

        Args:
            config: Application configuration (tunnel section used).
            logger: Optional pre-configured logger.  Falls back to Loguru.
            frp_binary: Path or name of the frpc executable.
        """
        self.config = config
        self.frp_binary = frp_binary
        self.config_gen = FrpConfigGenerator(config)
        self.logger = logger or loguru.logger.bind(module="tunnel")

        self._process: Optional[subprocess.Popen] = None
        self._status: str = "disconnected"
        self._start_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Generate frpc config and launch the frpc subprocess.

        Returns:
            True if the process was started successfully.
        """
        with self._lock:
            if self._process and self._process.poll() is None:
                self.logger.warning("frpc is already running (PID {})", self._process.pid)
                return False

            self._stop_event.clear()
            self._connected_event.clear()

            # Write config
            try:
                self.config_gen.write(self.CONFIG_PATH)
            except OSError as exc:
                self.logger.error("Failed to write frpc config: {}", exc)
                return False

            # Start frpc binary
            try:
                self._process = subprocess.Popen(
                    [self.frp_binary, "-c", self.CONFIG_PATH],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except FileNotFoundError:
                self.logger.error("frpc binary not found: {}", self.frp_binary)
                self._status = "error"
                return False
            except OSError as exc:
                self.logger.error("Failed to start frpc: {}", exc)
                self._status = "error"
                return False

            self._status = "connecting"
            self._start_time = datetime.now()
            self.logger.info("frpc started (PID {})", self._process.pid)

            # Background monitor
            self._monitor_thread = threading.Thread(
                target=self._monitor_process,
                daemon=True,
            )
            self._monitor_thread.start()

            return True

    def stop(self) -> bool:
        """Stop the frpc subprocess gracefully (terminate → kill).

        Returns:
            True if the process was stopped or was already stopped.
        """
        with self._lock:
            self._stop_event.set()
            proc = self._process
            if proc is None or proc.poll() is not None:
                self._status = "disconnected"
                self._process = None
                return True

            pid = proc.pid
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.logger.warning("frpc did not terminate; killing (PID {})", pid)
                    proc.kill()
                    proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.logger.error("frpc refused to die (PID {}); zombie process!", pid)
            except OSError as exc:
                self.logger.error("Error stopping frpc: {}", exc)

            if proc.poll() is not None:
                self._process = None
                self._status = "disconnected"
                self._start_time = None
                self._connected_event.clear()
                self.logger.info("frpc stopped")
                return True
            else:
                self._status = "error"
                self.logger.error("frpc stop failed; process may still be alive")
                return False

    def restart(self) -> bool:
        """Convenience: stop then start frpc."""
        self.stop()
        time.sleep(0.5)
        return self.start()

    def reload_and_restart(self) -> bool:
        """Reload config from the YAML file and restart frpc."""
        from config.loader import load_config
        try:
            new_cfg = load_config("config/config.yaml")
        except SystemExit:
            self.logger.error("配置重载失败（校验未通过），保持当前配置")
            return False
        except Exception as exc:
            self.logger.error("配置重载异常: {}", exc)
            return False

        self.config = new_cfg
        self.config_gen = FrpConfigGenerator(new_cfg)
        self.logger.info("配置已从文件重新加载，正在重启 frpc...")
        return self.restart()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Return True if the frpc subprocess is currently alive."""
        proc = self._process
        return proc is not None and proc.poll() is None

    def is_connected(self) -> bool:
        """Return True if the frp tunnel has reported a successful login."""
        return self._connected_event.is_set()

    def get_status(self) -> Dict:
        """Return a structured status dictionary suitable for API responses."""
        with self._lock:
            running = self.is_running()
            connected = self._connected_event.is_set()
            uptime_str = self._format_uptime()

            if running and connected:
                status = "connected"
            elif running and not connected:
                status = "connecting"
            else:
                status = self._status

            mappings: List[Dict] = []
            for key in self.config.tunnel.enabled_ports:
                mapping = self.config.tunnel.mapping.get(key)
                if mapping is None:
                    continue
                mappings.append({
                    "name": key,
                    "localPort": mapping.local_port,
                    "remotePort": mapping.remote_port,
                    "protocol": mapping.protocol.upper(),
                    "status": "active" if (running and connected) else "inactive",
                })

            return {
                "status": status,
                "server": f"{self.config.tunnel.server_addr}:{self.config.tunnel.server_port}",
                "uptime": uptime_str,
                "activeTunnels": str(len(mappings)) if running else "0",
                "mappings": mappings,
            }

    def update_mapping(self, enabled_ports: List[str]) -> bool:
        """Change enabled port mappings and restart frpc."""
        self.config_gen.update_mapping(enabled_ports)
        return self.restart()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _monitor_process(self) -> None:
        """Read frpc stdout and update state.  Exits when the process dies."""
        proc = self._process
        if not proc or not proc.stdout:
            return

        reader_thread = threading.Thread(
            target=self._read_stream, args=(proc.stdout,), daemon=True
        )
        reader_thread.start()

        proc.wait()
        reader_thread.join(timeout=2)

        with self._lock:
            # Stale monitor guard: if start() replaced the process while
            # we were blocked on wait(), exit silently.
            if self._process is not proc:
                return

            self._connected_event.clear()
            if not self._stop_event.is_set():
                self.logger.warning("frpc exited (code {})", proc.returncode)
                self._status = "disconnected"

    def _read_stream(self, stream) -> None:
        """Read lines from the merged stdout/stderr stream and update state."""
        try:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                self._process_line(line)
                self.logger.info("frpc: {}", line)
        except ValueError:
            pass

    def _process_line(self, line: str) -> None:
        """Parse a single frpc output line for state changes."""
        lower = line.lower()

        # Login / node connection success
        if any(phrase in lower for phrase in (
            "login to server success",
            "连接节点成功",
        )):
            with self._lock:
                self._status = "connected"
            self._connected_event.set()

        # Tunnel started successfully
        elif any(phrase in lower for phrase in (
            "start proxy success",
            "隧道启动成功",
        )):
            self._connected_event.set()

        # Session / connection closed
        elif any(phrase in lower for phrase in (
            "session closed",
            "连接已断开",
            "数据连接断开",
        )):
            with self._lock:
                self._status = "disconnected"
            self._connected_event.clear()

    def _format_uptime(self) -> str:
        """Return a human-readable uptime string."""
        if not self._start_time or not self.is_running():
            return "0分钟"

        delta: timedelta = datetime.now() - self._start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60

        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}分钟")
        return " ".join(parts)
