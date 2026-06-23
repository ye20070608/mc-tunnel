"""TCP proxy with Minecraft protocol sniffing.

Listens on an external-facing port, inspects the first few bytes of every
connection, and either proxies to the local MC server (Java Edition) or
rejects the connection (HTTP / unknown protocols).

Protocol detection
------------------
* ``0xFE`` first byte                  → legacy MC server list ping
* VarInt packet-length + ``0x00``      → modern MC handshake
* ASCII alphabetic first byte          → HTTP request (rejected)
* Anything else                         → closed with a warning

The proxy runs in a background thread with its own ``asyncio`` event loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

import loguru

from core.proxy.stats import ProxyStats


# ###########################################################################
# VarInt decoder
# ###########################################################################


def _read_varint(data: bytes) -> Optional[tuple]:
    """Try to decode a Minecraft-style VarInt from *data*.

    Args:
        data: Raw bytes from the connection start.

    Returns:
        ``(decoded_value, bytes_consumed)`` on success, or ``None`` if
        the VarInt is incomplete (more bytes needed).
    """
    result = 0
    for i, b in enumerate(data):
        result |= (b & 0x7F) << (7 * i)
        if not (b & 0x80):
            return result, i + 1
    return None


def _detect_protocol(first_bytes: bytes) -> str:
    """Identify the protocol from the initial bytes of a TCP connection.

    Returns one of ``'mc_legacy'``, ``'mc_modern'``, ``'http'``, or
    ``'unknown'``.
    """
    if not first_bytes:
        return "unknown"

    # -- Legacy MC server list ping -----------------------------------------
    if first_bytes[0] == 0xFE:
        return "mc_legacy"

    # -- Modern MC: VarInt(packet_length) + 0x00(handshake ID) ---------------
    varint_result = _read_varint(first_bytes)
    if varint_result is not None:
        length, consumed = varint_result
        if consumed < len(first_bytes) and first_bytes[consumed] == 0x00:
            if 1 <= length <= 256:  # sanity check
                return "mc_modern"

    # -- HTTP: leading ASCII letter ------------------------------------------
    # RFC 7230 methods: GET, POST, HEAD, PUT, DELETE, CONNECT, OPTIONS,
    # TRACE, PATCH  —  all start with A-Z
    if 0x41 <= first_bytes[0] <= 0x5A or 0x61 <= first_bytes[0] <= 0x7A:
        return "http"

    return "unknown"


# ###########################################################################
# Proxy server
# ###########################################################################


class MCProxyServer:
    """Async TCP proxy with MC protocol sniffing.

    Args:
        listen_port: Port the proxy listens on (typically 25565).
        mc_host: MC server hostname (e.g. ``'127.0.0.1'``).
        mc_port: MC server port (typically 25565).
        intro_url: URL to redirect HTTP clients to (e.g. ``'https://...'`` when SSL enabled).
        logger: Optional pre-configured logger.  Falls back to Loguru.
    """

    def __init__(
        self,
        listen_port: int,
        mc_host: str,
        mc_port: int,
        intro_url: str = "",
        logger=None,
    ) -> None:
        self.listen_port = listen_port
        self.mc_host = mc_host
        self.mc_port = mc_port
        self.intro_url = intro_url
        self.logger = logger or loguru.logger.bind(module="proxy")
        self.stats = ProxyStats()

        self._server: Optional[asyncio.Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the proxy in a background thread.

        Blocks briefly until the asyncio server is listening.
        """
        if self._thread and self._thread.is_alive():
            self.logger.warning("MCProxyServer is already running")
            return

        self._ready.clear()
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout=10):
            self.logger.error("MCProxyServer failed to start within 10 s")
            raise RuntimeError("MCProxyServer start timeout")

    def stop(self) -> None:
        """Stop the proxy and shut down the background event loop."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
            self._loop = None
            self._server = None

    def is_running(self) -> bool:
        """Return True if the background thread and server are alive."""
        return self._thread is not None and self._thread.is_alive()

    def get_stats(self) -> dict:
        """Return a snapshot of connection and traffic statistics."""
        return self.stats.get_stats()

    # ------------------------------------------------------------------
    # Internal: asyncio runner
    # ------------------------------------------------------------------

    def _run_async(self) -> None:
        """Entry point for the background thread: own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        try:
            loop.run_until_complete(self._start_server())
            self._ready.set()
            loop.run_forever()
        except Exception as exc:
            self.logger.error("MCProxyServer event loop error: {}", exc)
            self._ready.set()
        finally:
            loop.close()

    async def _start_server(self) -> None:
        """Create the asyncio TCP server."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            host="0.0.0.0",
            port=self.listen_port,
        )
        self.logger.info(
            "MCProxyServer listening on 0.0.0.0:{} → {}:{}",
            self.listen_port,
            self.mc_host,
            self.mc_port,
        )

    async def _shutdown(self) -> None:
        """Close the server and stop the event loop."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._loop:
            self._loop.stop()

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Inspect and proxy a single TCP connection."""
        peername = writer.get_extra_info("peername", ("?", 0))
        client_ip = peername[0] if isinstance(peername, tuple) else str(peername)

        try:
            # Read up to 32 bytes for protocol detection
            data = await asyncio.wait_for(reader.read(32), timeout=5.0)
            if not data:
                return

            proto = _detect_protocol(data)

            if proto in ("mc_legacy", "mc_modern"):
                await self._proxy_mc(reader, writer, data, client_ip)
            elif proto == "http":
                await self._reject_http(writer, client_ip)
            else:
                await self._reject_unknown(writer, client_ip)

        except asyncio.TimeoutError:
            self.stats.record_connection("unknown")
            self.logger.warning("Read timeout from {}", client_ip)
        except ConnectionError:
            pass  # client disconnected — nothing to log
        except Exception as exc:
            self.logger.error("Proxy error for {}: {}", client_ip, exc)
            self.stats.record_connection("unknown")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    # ------------------------------------------------------------------
    # Proxy modes
    # ------------------------------------------------------------------

    async def _proxy_mc(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        initial_data: bytes,
        client_ip: str,
    ) -> None:
        """Forward a connection to the MC server and relay bidirectionally."""
        self.stats.record_connection("mc")
        self.logger.info("MC connection from {}", client_ip)

        try:
            mc_reader, mc_writer = await asyncio.wait_for(
                asyncio.open_connection(self.mc_host, self.mc_port),
                timeout=5.0,
            )
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            self.logger.warning("Failed to connect to MC server: {}", exc)
            self.stats.record_disconnection()
            return

        try:
            # Forward the initial sniffed bytes
            mc_writer.write(initial_data)
            await mc_writer.drain()
            self.stats.record_bytes(len(initial_data), 0)

            await asyncio.gather(
                self._relay(client_reader, mc_writer, "upstream"),
                self._relay(mc_reader, client_writer, "downstream"),
            )
        except Exception:
            pass
        finally:
            try:
                mc_writer.close()
                await mc_writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self.stats.record_disconnection()
            self.logger.info("MC connection closed from {}", client_ip)

    async def _reject_http(self, writer: asyncio.StreamWriter, client_ip: str) -> None:
        """Reject an HTTP connection with a 302 redirect (or close)."""
        self.stats.record_connection("http")
        self.logger.info("HTTP blocked from {}", client_ip)

        if self.intro_url:
            response = (
                f"HTTP/1.1 302 Found\r\n"
                f"Location: {self.intro_url}\r\n"
                f"Content-Length: 0\r\n"
                f"Connection: close\r\n\r\n"
            )
            try:
                writer.write(response.encode())
                await writer.drain()
            except (ConnectionError, OSError):
                pass

    async def _reject_unknown(self, writer: asyncio.StreamWriter, client_ip: str) -> None:
        """Close a connection with unknown protocol."""
        self.stats.record_connection("unknown")
        self.logger.warning("Unknown protocol blocked from {}", client_ip)

    # ------------------------------------------------------------------
    # Bidirectional relay
    # ------------------------------------------------------------------

    async def _relay(
        self,
        src: asyncio.StreamReader,
        dst: asyncio.StreamWriter,
        direction: str,
    ) -> None:
        """Read from *src* and write to *dst* until EOF.

        *direction* controls byte accounting:
        ``'upstream'`` means data from the client is counted as incoming;
        ``'downstream'`` means data from the MC server is counted as outgoing.
        """
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
                if direction == "upstream":
                    self.stats.record_bytes(len(chunk), 0)
                else:
                    self.stats.record_bytes(0, len(chunk))
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                dst.close()
            except (ConnectionError, OSError):
                pass
