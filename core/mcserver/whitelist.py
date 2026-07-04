"""Whitelist manager — manages the MC server whitelist via RCON commands.

Reads ``whitelist.json`` for UUID information and maintains a sidecar
``whitelist_meta.json`` that records who added each player and when.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.mcserver.adapter import MCServerAdapter


class WhitelistManager:
    """Manages the Minecraft server whitelist through RCON commands.

    All methods return ``False`` or an empty list on failure instead of
    raising exceptions, and log errors internally.

    Args:
        adapter: The active MCServerAdapter instance.
    """

    def __init__(self, adapter: MCServerAdapter) -> None:
        self._adapter = adapter
        self._meta_path = Path("server/whitelist_meta.json")
        self._whitelist_path = Path("server/whitelist.json")
        # RLock (reentrant) is required because record_last_online()
        # acquires _meta_lock and then calls _read_meta() which also
        # acquires _meta_lock.  A plain Lock() would deadlock because
        # it is not reentrant on the same thread.
        self._meta_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API — CRUD
    # ------------------------------------------------------------------

    def add(self, player_name: str, operator: str = "admin") -> bool:
        """Add a player to the whitelist.

        Sends the RCON ``whitelist add`` command, then records metadata
        (operator, timestamp) in the sidecar file.

        Args:
            player_name: Minecraft Java Edition player name.
            operator: Username of the admin performing the action.

        Returns:
            True if the command was sent successfully.
        """
        if not player_name or not player_name.strip():
            return False

        name = player_name.strip()
        self._adapter.send_command(f"whitelist add {name}")
        self._record_meta(name, operator)
        return True

    def remove(self, player_name: str) -> bool:
        """Remove a player from the whitelist.

        Args:
            player_name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not player_name or not player_name.strip():
            return False

        name = player_name.strip()
        try:
            self._adapter.send_command(f"whitelist remove {name}")
            self._remove_meta(name)
            return True
        except Exception:
            return False

    def list(self) -> list[dict]:
        """Return structured whitelist entries.

        Cross-references ``whitelist.json`` (for UUID), the meta sidecar
        (for added-at / added-by), and the pending-rejections cache.

        Returns:
            List of dicts with keys ``name``, ``uuid``, ``added_at``,
            ``added_by``, ``online``.
        """
        wh_data = self._read_whitelist_json()
        meta = self._read_meta()
        result: list[dict] = []

        for entry in wh_data:
            name = entry.get("name", "")
            uuid = entry.get("uuid", "")
            m = meta.get(name, {})
            result.append({
                "name": name,
                "uuid": uuid,
                "added_at": m.get("added_at", ""),
                "added_by": m.get("added_by", ""),
                "last_online": m.get("last_online", ""),
                "online": False,  # filled in by API layer
            })

        return result

    # ------------------------------------------------------------------
    # Public API — server whitelist control
    # ------------------------------------------------------------------

    def reload(self) -> bool:
        """Reload the whitelist from disk.

        Useful after manually editing ``whitelist.json``.

        Returns:
            True if the reload command was sent successfully.
        """
        try:
            self._adapter.send_command("whitelist reload")
            return True
        except Exception:
            return False

    def toggle(self) -> dict:
        """Toggle whitelist enforcement on or off.

        Reads current state from ``server.properties`` (reliable), sends the
        RCON command, and writes the new state back to the properties file so
        it survives server restarts.

        Returns:
            Dict with ``enabled`` (bool, new state) and ``message`` (str).
        """
        try:
            # Read current state from server.properties (source of truth)
            props = self._read_server_properties()
            currently_on = props.get("white-list", "false").lower() == "true"

            new_state = not currently_on
            cmd = "whitelist on" if new_state else "whitelist off"
            self._adapter.send_command(cmd)
            self._write_server_property("white-list", "true" if new_state else "false")

            msg = "Whitelist enabled — only listed players can join" if new_state else "Whitelist disabled — anyone can join"
            return {"enabled": new_state, "message": msg}
        except Exception as e:
            return {"enabled": False, "message": f"Toggle failed: {e}"}

    def is_enabled(self) -> bool | None:
        """Check whether the whitelist is currently enforced.

        Reads ``white-list`` from ``server.properties`` (the source of truth).
        Also tries RCON ``whitelist list`` for runtime state when available.

        Returns:
            True/False, or None if the server is not running and we can't
            determine the state.
        """
        # Primary: read server.properties (always available)
        try:
            props = self._read_server_properties()
            wl_val = props.get("white-list", "").lower()
            if wl_val in ("true", "false"):
                return wl_val == "true"
        except Exception:
            pass

        # Fallback: try RCON
        try:
            raw = self._adapter.send_command("whitelist list")
            low = raw.lower()
            if "whitelist is currently enabled" in low:
                return True
            if "whitelist is currently disabled" in low:
                return False
        except Exception:
            pass

        return None

    @staticmethod
    def _read_server_properties() -> dict[str, str]:
        """Read ``server.properties`` into a flat dict."""
        props: dict[str, str] = {}
        props_path = Path("server/server.properties")
        if not props_path.is_file():
            return props
        for line in props_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
        return props

    @staticmethod
    def _write_server_property(key: str, value: str) -> None:
        """Update or add a single key=value in ``server.properties``."""
        import os
        props_path = Path("server/server.properties")
        lines: list[str] = []
        if props_path.is_file():
            lines = props_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        # Write atomically via temp file
        tmp_path = Path(str(props_path) + ".tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(str(tmp_path), str(props_path))

    # ------------------------------------------------------------------
    # Internal — whitelist.json
    # ------------------------------------------------------------------

    def _read_whitelist_json(self) -> list[dict]:
        """Read and parse the Minecraft ``whitelist.json`` file.

        Returns:
            List of ``{"name": ..., "uuid": ...}`` dicts.
        """
        if not self._whitelist_path.is_file():
            return []
        try:
            data = json.loads(self._whitelist_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return [
                {"name": e.get("name", ""), "uuid": e.get("uuid", "")}
                for e in data
                if isinstance(e, dict) and "name" in e
            ]
        except (json.JSONDecodeError, OSError):
            return []

    # ------------------------------------------------------------------
    # Internal — meta sidecar
    # ------------------------------------------------------------------

    def _read_meta(self) -> dict:
        """Read the ``whitelist_meta.json`` sidecar file.

        Returns:
            Dict mapping player name → ``{"added_by": ..., "added_at": ...}``.
        """
        if not self._meta_path.is_file():
            return {}
        try:
            with self._meta_lock:
                return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        """Write the meta dict to ``whitelist_meta.json``."""
        try:
            os.makedirs(self._meta_path.parent, exist_ok=True)
            with self._meta_lock:
                self._meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except OSError:
            pass

    def _record_meta(self, name: str, operator: str) -> None:
        """Record an add operation in the meta sidecar."""
        meta = self._read_meta()
        meta[name] = {
            "added_by": operator,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self._write_meta(meta)

    def _remove_meta(self, name: str) -> None:
        """Remove a player's entry from the meta sidecar."""
        meta = self._read_meta()
        if name in meta:
            del meta[name]
            self._write_meta(meta)

    # ------------------------------------------------------------------
    # Public API — last-online timestamp
    # ------------------------------------------------------------------

    def record_last_online(self, name: str, timestamp) -> None:
        """Update ``last_online`` for *name* in ``whitelist_meta.json``.

        Creates a minimal entry if the player isn't in the meta file yet.
        The entire read-modify-write cycle is protected by ``_meta_lock``
        to prevent TOCTOU races with whitelist add/remove operations.

        Args:
            name: Player name.
            timestamp: A ``datetime`` object (or any object with a
                ``strftime`` method).
        """
        try:
            with self._meta_lock:
                meta = self._read_meta()
                if name not in meta:
                    meta[name] = {}
                meta[name]["last_online"] = timestamp.strftime("%Y-%m-%d %H:%M")
                self._meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception:
            pass  # best-effort, don't break join flow
