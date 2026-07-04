"""Generic subprocess lifecycle manager."""
from __future__ import annotations

import collections
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

# Regex for ANSI escape sequences (CSI codes like \x1b[93m, \x1b[0m).
# PaperMC outputs these to colorize player join/leave messages when
# Jansi is active.  Stripped early so they do not corrupt regex-based
# player-name detection in stdout callbacks.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Patterns for internal/non-game console lines that should be hidden
# from the user-facing console view.
_INTERNAL_PATTERNS = [
    re.compile(p) for p in [
        r"Thread RCON Client .* (?:started|shutting down|stopping)",
        r"RCON Client .* (?:connected|disconnected)",
        r"\[RCON\] ",
        r"RCON .*: \d+",
    ]
]


def _is_internal_line(text: str) -> bool:
    """Return True if *text* is an internal/non-game console line."""
    for pattern in _INTERNAL_PATTERNS:
        if pattern.search(text):
            return True
    return False


class ProcessManager:
    """Generic subprocess lifecycle manager.

    Manages a subprocess from start to stop, with optional auto-restart
    on unexpected exit.  All public methods are thread-safe.

    Attributes:
        name: Human-readable label for the managed process.
    """

    def __init__(
        self,
        name: str,
        cmd: list[str],
        logger,
        auto_restart: bool = False,
        restart_max: int = 3,
        stdout_callback: Callable[[str], None] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        """Initialize the process manager.

        Args:
            name: Human-readable label for logging.
            cmd: Command and arguments for ``subprocess.Popen``.
            logger: Loguru logger bound with a module name.
            auto_restart: If True, restart the process on unexpected exit.
            restart_max: Maximum number of auto-restart attempts.
            stdout_callback: Optional callback invoked for each line of stdout.
            cwd: Working directory for the subprocess (None = inherit from parent).
        """
        self._name = name
        self._cmd = cmd
        self._log = logger
        self._auto_restart = auto_restart
        self._restart_max = restart_max
        self._stdout_callback = stdout_callback
        self._cwd = str(cwd) if cwd is not None else None

        self._restart_count = 0
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop_requested = False
        self._monitor_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None

        # Ring buffer for recent console output (thread-safe)
        self._console_buffer: collections.deque[str] = collections.deque(maxlen=500)
        self._buffer_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        """Mark that a graceful stop was requested externally.

        Call this *before* triggering a shutdown via an out-of-band
        mechanism (e.g. RCON ``/stop``).  It tells the auto-restart
        monitor that the impending exit is intentional, preventing a
        false-positive "unexpected crash" restart.
        """
        with self._lock:
            self._stop_requested = True

    def start(self) -> bool:
        """Start the subprocess.

        Returns:
            True if the process was started successfully, False if it was
            already running or if the launch failed.
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._log.warning("{} is already running (pid={})", self._name, self._process.pid)
                return False

            try:
                self._stop_requested = False
                self._process = subprocess.Popen(
                    self._cmd,
                    cwd=self._cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self._log.info("{} started (pid={})", self._name, self._process.pid)

                self._start_reader()
                if self._auto_restart:
                    self._start_monitor()

                return True
            except (OSError, subprocess.SubprocessError) as e:
                self._log.error("Failed to start {}: {}", self._name, e)
                self._process = None
                return False

    def stop(self, timeout: float = 15.0) -> bool:
        """Stop the subprocess.

        Sends SIGTERM first (``terminate()`` on Windows), waits *timeout*
        seconds, then SIGKILL if still running.

        Args:
            timeout: Seconds to wait for graceful shutdown.

        Returns:
            True if the process was stopped or was not running.
        """
        with self._lock:
            self._stop_requested = True
            proc = self._process
            if proc is None or proc.poll() is not None:
                self._log.debug("{} is not running, nothing to stop", self._name)
                return True

            try:
                proc.terminate()
                self._log.info("{} terminating (pid={})", self._name, proc.pid)

                try:
                    proc.wait(timeout=timeout)
                    self._log.info("{} stopped gracefully (pid={})", self._name, proc.pid)
                except subprocess.TimeoutExpired:
                    self._log.warning(
                        "{} did not stop in {:.1f}s, sending SIGKILL",
                        self._name,
                        timeout,
                    )
                    proc.kill()
                    proc.wait()
                    self._log.info("{} killed (pid={})", self._name, proc.pid)

                self._process = None
                self._restart_count = 0
                return True
            except (OSError, subprocess.SubprocessError) as e:
                self._log.error("Failed to stop {}: {}", self._name, e)
                return False

    def restart(self) -> bool:
        """Restart the subprocess.

        Stops the current instance (if running) and starts a new one.

        Returns:
            True if the restart was successful.
        """
        self._log.info("Restarting {}...", self._name)
        if not self.stop():
            return False
        # Ensure the old stdout reader has drained the dead process's pipe
        # before we launch a new process — otherwise _start_reader may see
        # the old thread still alive and skip creating a reader for the new
        # child, which fills the pipe buffer and deadlocks the process.
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)
        time.sleep(0.5)
        return self.start()

    def is_running(self) -> bool:
        """Check whether the subprocess is currently running.

        Returns:
            True if the process is alive, False otherwise.
        """
        proc = self._process
        if proc is None:
            return False
        return proc.poll() is None

    def wait(self) -> int:
        """Block until the subprocess exits.

        Returns:
            The exit code of the process, or -1 if no process was started.
        """
        proc = self._process
        if proc is None:
            return -1
        return proc.wait()

    def get_pid(self) -> int | None:
        """Return the PID of the running process, or None."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return None
        return proc.pid

    def send_signal(self, sig: int) -> None:
        """Send a signal to the subprocess.

        Args:
            sig: Signal number (e.g. ``signal.SIGTERM``, ``signal.SIGKILL``).
        """
        proc = self._process
        if proc and proc.poll() is None:
            proc.send_signal(sig)
            self._log.debug("Sent signal {} to {} (pid={})", sig, self._name, proc.pid)
        else:
            self._log.warning("Cannot send signal to {}: not running", self._name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_reader(self) -> None:
        """Start the background thread that reads stdout and pipes it to the logger.

        If a previous reader is still alive (e.g. draining the old process's
        pipe after a restart), wait for it to finish before starting a fresh
        one.  This prevents the new subprocess from starting without a reader,
        which would fill the pipe buffer and deadlock the child.
        """
        old = self._reader_thread
        if old is not None and old.is_alive():
            old.join(timeout=3.0)
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"out-{self._name}",
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        """Read process stdout line-by-line and forward to the logger.

        Runs until the subprocess stdout pipe is closed (EOF) or the
        process exits.  The outer ``while True`` loop ensures that
        transient exceptions (e.g. a callback deadlock, a temporary
        I/O hiccup) cannot permanently kill the reader — it restarts
        automatically as long as the subprocess is still alive.
        """
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        while True:  # outer: survive transient exceptions
            try:
                while True:  # inner: read lines
                    line = proc.stdout.readline()
                    if not line:
                        # EOF on the pipe — if the process is still alive
                        # this is anomalous (pipe broken / stdout handle
                        # closed).
                        if proc.poll() is None:
                            self._log.error(
                                "{} stdout pipe closed unexpectedly "
                                "(process PID {} still running)",
                                self._name,
                                proc.pid,
                            )
                        return  # EOF — exit cleanly

                    text = line.rstrip("\n\r")
                    if not text:
                        continue

                    # Strip ANSI escape sequences before downstream
                    # processing so that PaperMC/Jansi color codes
                    # (e.g. \x1b[93m) do not corrupt regex-based
                    # player-name detection or display as garbage.
                    text = _ANSI_RE.sub("", text)
                    if not text:
                        continue

                    # Log the raw line — protect the reader thread against
                    # Loguru failures (disk full, permission change, etc.).
                    try:
                        self._log.info("[{}] {}", self._name, text)
                    except Exception:
                        pass

                    # Append to ring buffer (thread-safe).
                    # Filter internal RCON connection noise — these are
                    # implementation details, not game content.
                    if not _is_internal_line(text):
                        with self._buffer_lock:
                            self._console_buffer.append(text)

                    if self._stdout_callback:
                        try:
                            self._stdout_callback(text)
                        except Exception:
                            pass
            except Exception:
                import traceback
                try:
                    self._log.error(
                        "{} reader loop crashed (will restart):\n{}",
                        self._name,
                        traceback.format_exc(),
                    )
                except Exception:
                    pass
                # Brief sleep to avoid busy-looping on persistent errors
                time.sleep(0.1)
                # If the process has exited, there is nothing left to read
                if proc.poll() is not None:
                    return

    def get_console_buffer(self, limit: int = 100) -> list[str]:
        """Return recent lines from the console ring buffer.

        Args:
            limit: Maximum number of lines to return (newest first).

        Returns:
            List of most recent console output lines.
        """
        with self._buffer_lock:
            lines = list(self._console_buffer)
        return lines[-limit:]

    def _start_monitor(self) -> None:
        """Start the background monitor thread for auto-restart.

        Joins any previous monitor thread before launching a new one so
        that at most one monitor watches the current process at a time.
        """
        old = self._monitor_thread
        if old is not None and old.is_alive():
            old.join(timeout=3.0)
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name=f"mon-{self._name}",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Wait for the process to exit, then decide whether to restart.

        Only runs when ``auto_restart`` is True.  After an unexpected exit
        the process is restarted up to ``restart_max`` times.
        """
        proc = self._process
        if proc is None:
            return

        try:
            proc.wait()
        except Exception as e:
            self._log.error("{} monitor error: {}", self._name, e)
            return

        with self._lock:
            if self._stop_requested:
                self._log.info("{} stopped by request, monitor exiting", self._name)
                return

            self._restart_count += 1
            if self._restart_count > self._restart_max:
                self._log.error(
                    "{} exited unexpectedly (attempt {}/{}), giving up",
                    self._name,
                    self._restart_count,
                    self._restart_max,
                )
                self._process = None
                return

            self._log.warning(
                "{} exited unexpectedly (attempt {}/{}), restarting...",
                self._name,
                self._restart_count,
                self._restart_max,
            )
            self._process = None

        self.start()

    @property
    def name(self) -> str:
        """Return the process label."""
        return self._name
