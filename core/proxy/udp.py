"""UDP proxy placeholder for Bedrock edition support (Phase 2).

The stub logs lifecycle events but performs no actual UDP forwarding.
The full implementation will handle Minecraft Bedrock (19132/UDP) in a
future iteration.
"""

from __future__ import annotations

from typing import Any

import loguru


class UDPProxyStub:
    """No-op UDP proxy stub.

    Args:
        config: Application config (unused until Phase 2).
        logger: Optional pre-configured logger.  Falls back to Loguru.
    """

    def __init__(self, config: Any, logger=None) -> None:
        self.logger = logger or loguru.logger.bind(module="proxy")

    def start(self) -> None:
        """Log startup (no-op)."""
        self.logger.info("UDP proxy stub started (no-op)")

    def stop(self) -> None:
        """Stop the stub (no-op)."""
        pass
