"""Whitelist manager — manages the MC server whitelist via RCON commands."""
from __future__ import annotations

import re
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, player_name: str) -> bool:
        """Add a player to the whitelist.

        Args:
            player_name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not player_name or not player_name.strip():
            return False

        try:
            self._adapter.send_command(f"whitelist add {player_name.strip()}")
            return True
        except Exception:
            return False

    def remove(self, player_name: str) -> bool:
        """Remove a player from the whitelist.

        Args:
            player_name: Minecraft Java Edition player name.

        Returns:
            True if the command was sent successfully.
        """
        if not player_name or not player_name.strip():
            return False

        try:
            self._adapter.send_command(f"whitelist remove {player_name.strip()}")
            return True
        except Exception:
            return False

    def list(self) -> list[str]:
        """Retrieve the list of whitelisted players.

        Returns:
            List of player names (may be empty).
        """
        try:
            raw = self._adapter.send_command("whitelist list")
            return self._parse_whitelist(str(raw))
        except Exception:
            return []

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_whitelist(output: str) -> list[str]:
        """Parse the response of the ``/whitelist list`` command.

        Expected server output format::

            There are 3 whitelisted player(s):
            player1, player2, player3

        Args:
            output: Raw RCON response.

        Returns:
            List of player name strings.
        """
        if "whitelisted" not in output.lower():
            return []

        lines = output.splitlines()
        players_found: list[str] = []

        # Collect player names across all lines after the header
        for line in lines:
            # Try extracting after a colon first
            match = re.search(r":\s*(.+)", line)
            if match:
                remainder = match.group(1).strip()
                if remainder:
                    players_found.extend(
                        p.strip() for p in remainder.split(",") if p.strip()
                    )
                continue

            # Lines without a colon may contain the remainder of the list
            stripped = line.strip()
            if stripped and "," in stripped:
                players_found.extend(
                    p.strip() for p in stripped.split(",") if p.strip()
                )

        return players_found
