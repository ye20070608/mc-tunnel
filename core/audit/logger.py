"""Audit logging for sensitive administrative operations.

All security-relevant actions (MC server start/stop, whitelist changes,
tunnel config updates, password changes, failed logins) are recorded
here for accountability.

Storage format: JSON Lines (one JSON object per line) in ``logs/audit.log``.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import loguru


class AuditLogger:
    """Thread-safe audit logger.

    Writes JSON Lines to a dedicated file AND forwards a summary line to
    the main application logger.

    Args:
        log_path: Path to the JSON Lines audit file.
        logger: Optional pre-configured logger.  Falls back to Loguru.
    """

    def __init__(self, log_path: str = "logs/audit.log", logger=None) -> None:
        self.log_path = log_path
        self.logger = logger or loguru.logger.bind(module="audit")
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def log(
        self,
        operator: str,
        action: str,
        ip: str = "127.0.0.1",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an auditable operation.

        Args:
            operator: Username of the person performing the action.
            action: Short human-readable description (e.g. ``'mc.start'``).
            ip: Source IP address of the request.
            details: Optional structured payload (e.g. ``{"port": 25565}``).
        """
        entry: Dict[str, Any] = {
            "time": datetime.now().isoformat(),
            "operator": operator,
            "ip": ip,
            "action": action,
            "details": details or {},
        }

        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as exc:
                self.logger.error("Failed to write audit log: {}", exc)

        self.logger.info("AUDIT: {} {} from {}", operator, action, ip)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_logs(
        self,
        limit: int = 100,
        operator: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent audit log entries.

        Entries are returned newest-first.

        Args:
            limit: Maximum number of entries to return.
            operator: If set, only return entries for this operator.

        Returns:
            A list of dicts, each with keys ``time``, ``operator``, ``ip``,
            ``action``, ``details``.
        """
        entries: List[Dict[str, Any]] = []

        with self._lock:
            if not os.path.isfile(self.log_path):
                return entries

            try:
                with open(self.log_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry: Dict[str, Any] = json.loads(line)
                            if operator is None or entry.get("operator") == operator:
                                entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except OSError as exc:
                self.logger.error("Failed to read audit log: {}", exc)
                return entries

        entries.reverse()
        return entries[:limit]

    def export(self, output_path: str) -> str:
        """Copy the audit log to *output_path*.

        Args:
            output_path: Destination file path.

        Returns:
            The absolute (or provided) path of the copied file.
        """
        with self._lock:
            try:
                shutil.copy2(self.log_path, output_path)
            except OSError as exc:
                self.logger.error("Failed to export audit log: {}", exc)
                # If source doesn't exist, create an empty file at the target
                if not os.path.isfile(self.log_path):
                    try:
                        open(output_path, "w", encoding="utf-8").close()
                    except OSError:
                        pass

        return output_path
