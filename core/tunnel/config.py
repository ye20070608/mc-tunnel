"""frp client configuration (frpc.ini) generator.

Reads the tunnel section from a Config object and generates
standard frpc.ini content suitable for the frp client.
"""

from __future__ import annotations

from typing import Dict, List

from config.loader import Config


class FrpConfigGenerator:
    """Generates frpc.ini from the Config tunnel section.

    Supports multiple port mappings (TCP/UDP) with dynamic enable/disable.
    """

    def __init__(self, config: Config) -> None:
        """Initialize with a Config object.

        Args:
            config: Fully populated Config dataclass.
        """
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> str:
        """Generate frpc config content as a string.

        Supports two modes:

        - **Standard frp**: uses ``token`` for authentication (``token`` is set,
          ``user`` is empty).
        - **Sakura Frp**: uses ``user`` + ``auth_pass`` for authentication
          (``user`` is non-empty).  Adds ``sakura_mode``, ``login_fail_exit``,
          and per-proxy ``auth_pass``.

        Returns:
            Complete frpc config content (``frpc.ini`` or ``frpc.toml``).
        """
        tunnel = self.config.tunnel
        lines: list[str] = []
        is_sakura = bool(tunnel.user and tunnel.user.strip())

        lines.append("[common]")

        if is_sakura:
            # Sakura Frp mode
            lines.append(f"user = {tunnel.user}")
            lines.append(f"sakura_mode = true")  # forced when user is set
            lines.append(f"login_fail_exit = {'true' if tunnel.login_fail_exit else 'false'}")
            lines.append(f"server_addr = {tunnel.server_addr}")
            lines.append(f"server_port = {tunnel.server_port}")
        else:
            # Standard frp mode
            lines.append(f"server_addr = {tunnel.server_addr}")
            lines.append(f"server_port = {tunnel.server_port}")
            lines.append(f"token = {tunnel.token}")

        if tunnel.protocol in ("udp", "both"):
            lines.append("protocol = kcp")

        lines.append("")

        for key in tunnel.enabled_ports:
            mapping = tunnel.mapping.get(key)
            if mapping is None:
                continue

            lines.append(f"[{key}]")
            if is_sakura:
                lines.append(f"local_ip = 127.0.0.1")
            lines.append(f"type = {mapping.protocol}")
            lines.append(f"local_port = {mapping.local_port}")
            lines.append(f"remote_port = {mapping.remote_port}")
            # Per-proxy auth_pass (falls back to global tunnel.auth_pass)
            proxy_auth = mapping.auth_pass or tunnel.auth_pass
            if is_sakura and proxy_auth:
                lines.append(f"auth_pass = {proxy_auth}")
            lines.append("")

        return "\n".join(lines)

    def write(self, path: str = "frpc.ini") -> str:
        """Write generated frpc.ini to a file.

        Args:
            path: Destination file path.

        Returns:
            The absolute path of the written file.
        """
        content = self.generate()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def update_mapping(self, enabled_ports: List[str]) -> str:
        """Regenerate config with a new set of enabled port keys.

        This does **not** write to disk; call :meth:`write` afterwards
        if persistence is needed.

        Args:
            enabled_ports: New list of port mapping keys to enable.

        Returns:
            The new config content.
        """
        self.config.tunnel.enabled_ports = enabled_ports
        return self.generate()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_mappings(self) -> Dict[str, Dict]:
        """Return a human-readable summary of all available mappings.

        Includes both enabled and disabled mappings for display purposes.
        """
        result: Dict[str, Dict] = {}
        for key, mapping in self.config.tunnel.mapping.items():
            result[key] = {
                "local_port": mapping.local_port,
                "remote_port": mapping.remote_port,
                "protocol": mapping.protocol,
                "enabled": key in self.config.tunnel.enabled_ports,
            }
        return result
