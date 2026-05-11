"""'app bridge' - expose a local HCI transport as TCP/UDP H4."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pybluehost.cli._lifecycle import add_trace_arguments, trace_kwargs_from_args
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.core.errors import TransportError
from pybluehost.core.trace import BtsnoopSink, Direction, TraceEvent
from pybluehost.transport.base import Transport, TransportSink
from pybluehost.transport.h4 import H4Framer
from pybluehost.transport.spec import UART_SPEC_FORMAT, USB_SPEC_FORMAT

BridgeProtocol = Literal["tcp", "udp"]

DEFAULT_BRIDGE_PORT = 57123

logger = logging.getLogger(__name__)


class _BridgeSink(TransportSink):
    def __init__(self, bridge: HCITransportBridge) -> None:
        self._bridge = bridge

    async def on_transport_data(self, data: bytes) -> None:
        await self._bridge.send_frontend(data)

    async def on_transport_error(self, error: TransportError) -> None:
        logger.error("Backend transport error: %s", error)
        self._bridge.request_stop()


class _UDPFrontend(asyncio.DatagramProtocol):
    def __init__(self, bridge: HCITransportBridge) -> None:
        self._bridge = bridge

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self._bridge.handle_udp_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP frontend error: %s", exc)


class HCITransportBridge:
    """Bidirectional H4 bridge between a local transport and a network frontend."""

    def __init__(
        self,
        backend: Transport,
        *,
        protocol: BridgeProtocol,
        host: str,
        port: int,
        btsnoop: str | Path | None = None,
        hci_log: bool = False,
    ) -> None:
        if protocol not in ("tcp", "udp"):
            raise ValueError(f"Unsupported bridge protocol: {protocol!r}")
        if port < 0 or port > 65535:
            raise ValueError(f"Invalid bridge port: {port!r}")

        self._backend = backend
        self._protocol = protocol
        self._host = host
        self._port = port
        self._sink = _BridgeSink(self)
        self._stop_event = asyncio.Event()
        self._tcp_server: asyncio.AbstractServer | None = None
        self._tcp_writer: asyncio.StreamWriter | None = None
        self._tcp_write_lock = asyncio.Lock()
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._udp_peer = None
        self._listen_addr: tuple[str, int] | None = None
        self._btsnoop = BtsnoopSink(btsnoop) if btsnoop is not None else None
        self._hci_log = hci_log

    @property
    def listen_addr(self) -> tuple[str, int]:
        if self._listen_addr is None:
            raise RuntimeError("Bridge is not listening")
        return self._listen_addr

    async def start(self) -> None:
        self._backend.set_sink(self._sink)
        if not self._backend.is_open:
            await self._backend.open()

        if self._protocol == "tcp":
            self._tcp_server = await asyncio.start_server(
                self._handle_tcp_client,
                self._host,
                self._port,
            )
            sock = self._tcp_server.sockets[0]
            host, port = sock.getsockname()[:2]
            self._listen_addr = (str(host), int(port))
            logger.info("HCI bridge listening on tcp://%s:%d", host, port)
            return

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPFrontend(self),
            local_addr=(self._host, self._port),
        )
        self._udp_transport = transport  # type: ignore[assignment]
        host, port = transport.get_extra_info("sockname")[:2]
        self._listen_addr = (str(host), int(port))
        logger.info("HCI bridge listening on udp://%s:%d", host, port)

    async def wait_closed(self) -> None:
        await self._stop_event.wait()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def close(self) -> None:
        self.request_stop()

        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._tcp_server = None

        if self._tcp_writer is not None:
            self._tcp_writer.close()
            with contextlib.suppress(Exception):
                await self._tcp_writer.wait_closed()
            self._tcp_writer = None

        if self._udp_transport is not None:
            self._udp_transport.close()
            self._udp_transport = None

        self._backend.set_sink(None)
        await self._backend.close()
        if self._btsnoop is not None:
            await self._btsnoop.flush()
            await self._btsnoop.close()

    async def send_frontend(self, data: bytes) -> None:
        await self._record_packet(data, Direction.UP)
        if self._protocol == "tcp":
            await self._send_tcp(data)
            return
        self._send_udp(data)

    async def handle_udp_datagram(self, data: bytes, addr) -> None:
        self._udp_peer = addr
        logger.debug("UDP frontend -> backend %s bytes from %s", len(data), addr)
        await self._record_packet(data, Direction.DOWN)
        await self._backend.send(data)

    async def _send_tcp(self, data: bytes) -> None:
        writer = self._tcp_writer
        if writer is None:
            return
        async with self._tcp_write_lock:
            try:
                writer.write(data)
                await writer.drain()
            except Exception as exc:
                logger.warning("TCP frontend write failed: %s", exc)
                if self._tcp_writer is writer:
                    self._tcp_writer = None

    def _send_udp(self, data: bytes) -> None:
        if self._udp_transport is None or self._udp_peer is None:
            return
        self._udp_transport.sendto(data, self._udp_peer)

    async def _handle_tcp_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        if self._tcp_writer is not None:
            logger.warning("Rejecting extra TCP bridge client from %s", peer)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return

        logger.info("TCP bridge client connected from %s", peer)
        self._tcp_writer = writer
        framer = H4Framer()
        try:
            while not self._stop_event.is_set():
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for packet in framer.feed(chunk):
                    logger.debug("TCP frontend -> backend %s bytes", len(packet))
                    await self._record_packet(packet, Direction.DOWN)
                    await self._backend.send(packet)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("TCP bridge client error from %s: %s", peer, exc)
        finally:
            if self._tcp_writer is writer:
                self._tcp_writer = None
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            logger.info("TCP bridge client disconnected from %s", peer)

    async def _record_packet(self, data: bytes, direction: Direction) -> None:
        if self._hci_log:
            label = "RX" if direction == Direction.UP else "TX"
            logger.warning("[HCI %s] %s", label, data.hex(" "))
        if self._btsnoop is None:
            return
        await self._btsnoop.on_trace(
            TraceEvent(
                timestamp=time.time(),
                wall_clock=datetime.now(timezone.utc),
                source_layer="transport",
                direction=direction,
                raw_bytes=data,
                decoded=None,
                connection_handle=None,
                metadata={"bridge": self._protocol},
            )
        )


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}") from exc
    if port <= 0 or port > 65535:
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def register_bridge_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "bridge",
        help="Bridge a local UART/USB HCI transport to TCP/UDP H4",
    )
    add_trace_arguments(p)
    p.add_argument(
        "-t",
        "--transport",
        required=True,
        help=(
            "Local HCI transport: "
            f"{USB_SPEC_FORMAT} | {UART_SPEC_FORMAT}"
        ),
    )
    p.add_argument(
        "--protocol",
        choices=("tcp", "udp"),
        default="tcp",
        help="Network frontend protocol (default: tcp)",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Listen host (default: 127.0.0.1)",
    )
    p.add_argument(
        "--port",
        type=_parse_port,
        default=DEFAULT_BRIDGE_PORT,
        help=f"Listen port (default: {DEFAULT_BRIDGE_PORT})",
    )
    p.set_defaults(func=lambda args: asyncio.run(_run_bridge_command(args)))


async def _run_bridge_command(args: argparse.Namespace) -> int:
    stop_event = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)
    except RuntimeError:
        pass

    bridge: HCITransportBridge | None = None
    try:
        backend = await parse_transport_arg(args.transport)
        bridge = HCITransportBridge(
            backend,
            protocol=args.protocol,
            host=args.host,
            port=args.port,
            **trace_kwargs_from_args(args),
        )
        await bridge.start()
        host, port = bridge.listen_addr
        logger.info(
            "Bridge ready: %s://%s:%d -> %s",
            args.protocol,
            host,
            port,
            backend.info.description,
        )
        stop_task = asyncio.create_task(stop_event.wait())
        bridge_task = asyncio.create_task(bridge.wait_closed())
        done, pending = await asyncio.wait(
            {stop_task, bridge_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return 130 if stop_task in done else 1
    except Exception as exc:
        logger.error("Error: %s: %s", type(exc).__name__, exc)
        return 1
    finally:
        if bridge is not None:
            await bridge.close()
