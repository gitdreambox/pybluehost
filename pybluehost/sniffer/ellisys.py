"""Ellisys Bluetooth Analyzer injection — pure encoding + Windows backend."""
from __future__ import annotations

from pybluehost.core.trace import Direction


# H4 packet types (mirror pybluehost.hci.packets.HCI_*_PACKET constants)
_H4_COMMAND = 0x01
_H4_ACL = 0x02
_H4_SCO = 0x03
_H4_EVENT = 0x04
_H4_ISO = 0x05


def ellisys_packet_type(h4_type: int, direction: Direction) -> int:
    """Map (H4 packet type, direction) → Ellisys InjectedHciPacketType byte.

    See design spec §3.2. ACL/SCO/ISO have FromHost/FromController variants.
    """
    if h4_type == _H4_COMMAND:
        return 0x01
    if h4_type == _H4_EVENT:
        return 0x84
    if h4_type == _H4_ACL:
        return 0x02 if direction == Direction.DOWN else 0x82
    if h4_type == _H4_SCO:
        return 0x03 if direction == Direction.DOWN else 0x83
    if h4_type == _H4_ISO:
        return 0x05 if direction == Direction.DOWN else 0x85
    raise ValueError(f"unknown H4 packet type: 0x{h4_type:02X}")


import struct
from datetime import datetime, timezone


# Ellisys Service IDs / object tags (recovered from the working demo +
# bex400a_injection_api samples)
_ELLISYS_HCI_INJECTION_SERVICE_ID = 0x0002
_ELLISYS_HCI_INJECTION_SERVICE_VERSION = 0x01
_OBJ_DATETIME_NS = 0x02
_OBJ_BITRATE = 0x80
_OBJ_PACKET_TYPE = 0x81
_OBJ_PACKET_DATA = 0x82
_OBJ_CONTROLLER_INDEX = 0x83

# USB full-speed nominal bit rate (informational field in the injection packet)
ELLISYS_HCI_USB_FULL_SPEED_BITRATE = 12_000_000.0


def _utc_datetime_ns_fields(wall_clock: datetime) -> tuple[int, int, int, int, int]:
    """Return (year, month, day, ns_low, ns_high) where ns is nanoseconds
    since UTC midnight of that day, split into low u32 / high u16."""
    if wall_clock.tzinfo is not None:
        wall_clock = wall_clock.astimezone(timezone.utc)
    ns = (
        ((wall_clock.hour * 60 + wall_clock.minute) * 60 + wall_clock.second)
        * 1_000_000_000
        + wall_clock.microsecond * 1_000
    )
    return (
        wall_clock.year,
        wall_clock.month,
        wall_clock.day,
        ns & 0xFFFFFFFF,
        (ns >> 32) & 0xFFFF,
    )


def encode_ellisys_injection_packet(
    wall_clock: datetime,
    bit_rate: float,
    packet_type: int,
    hci_payload: bytes,
    controller_index: int = 0,
) -> bytes:
    """Encode an Ellisys HCI injection UDP packet (design spec §3.2 / §5.5).

    `packet_type` is an Ellisys InjectedHciPacketType byte (use
    `ellisys_packet_type(h4, direction)` to compute). `hci_payload` must NOT
    include the H4 type byte. Byte layout mirrors the working demo's
    `prepare_ellisys_hci_injection_packet`.
    """
    year, month, day, ns_low, ns_high = _utc_datetime_ns_fields(wall_clock)
    return b"".join([
        struct.pack(
            "<HB",
            _ELLISYS_HCI_INJECTION_SERVICE_ID,
            _ELLISYS_HCI_INJECTION_SERVICE_VERSION,
        ),
        struct.pack("<BHBBIH", _OBJ_DATETIME_NS, year, month, day, ns_low, ns_high),
        struct.pack("<BB", _OBJ_CONTROLLER_INDEX, controller_index),
        struct.pack("<Bf", _OBJ_BITRATE, bit_rate),
        struct.pack("<BB", _OBJ_PACKET_TYPE, packet_type),
        struct.pack("<B", _OBJ_PACKET_DATA),
        hci_payload,
    ])


import asyncio  # noqa: E402
import logging  # noqa: E402
import socket as _socket  # noqa: E402
import subprocess  # noqa: E402

from pybluehost.core.errors import SnifferError, SnifferUnavailableError  # noqa: E402
from pybluehost.sniffer.backend import SnifferBackend  # noqa: E402

logger = logging.getLogger(__name__)


# Default ports (sync with the working demo)
DEFAULT_ELLISYS_TCP_PORT = 46148
DEFAULT_ELLISYS_UDP_PORT = 24352


class EllisysBackend(SnifferBackend):
    """Ellisys analyzer integration via UDP HCI injection + PowerShell Ice setup.

    Design spec §6.1. `start()` is split into three helpers:
      - _launch_analyzer()  → Windows-only, spawns Ellisys.BluetoothAnalyzer.exe
      - _run_ice_setup()    → Windows-only, PowerShell + Ice.dll
      - _open_socket()      → cross-platform, UDP socket

    Tests use `skip_launch=True` to skip the Windows-only helpers and verify
    encoding + UDP transport against a local mock UDP server.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        udp_port: int = DEFAULT_ELLISYS_UDP_PORT,
        tcp_port: int = DEFAULT_ELLISYS_TCP_PORT,
        controller_index: int = 0,
        bit_rate: float = ELLISYS_HCI_USB_FULL_SPEED_BITRATE,
        ellisys_path: str | None = None,
        skip_launch: bool = False,
    ) -> None:
        self.host = host
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.controller_index = controller_index
        self.bit_rate = bit_rate
        self.ellisys_path = ellisys_path
        self.skip_launch = skip_launch
        self._sock: _socket.socket | None = None

    # ----------------------------------------------------------------- start

    async def start(self) -> None:
        if not self.skip_launch:
            await self._launch_analyzer()
            await self._run_ice_setup()
        self._open_socket()

    async def _launch_analyzer(self) -> None:
        """Spawn Ellisys.BluetoothAnalyzer.exe if not already running, wait until ready."""
        import sys
        from pathlib import Path

        from pybluehost.sniffer._ellisys_setup import wait_for_tcp_port

        if sys.platform != "win32":
            raise SnifferUnavailableError(
                "EllisysBackend requires Windows (analyzer is Windows-only)"
            )
        if self.ellisys_path is None:
            raise SnifferError(
                "EllisysBackend: analyzer path not set. "
                "Pass ellisys_path=... or use --virtual-sniffer=ellisys:ellisys-path=..."
            )
        analyzer_exe = Path(self.ellisys_path) / "Ellisys.BluetoothAnalyzer.exe"
        if not analyzer_exe.exists():
            raise SnifferError(f"Ellisys analyzer exe not found: {analyzer_exe}")
        subprocess.Popen(
            [
                str(analyzer_exe),
                f"/remote_control_port={self.tcp_port}",
                f"/injection_api_port={self.udp_port}",
                "/suffix=PTS",
            ],
            close_fds=True,
        )
        wait_for_tcp_port(self.host, self.tcp_port, timeout_s=60.0)

    async def _run_ice_setup(self) -> None:
        from pathlib import Path

        from pybluehost.sniffer._ellisys_setup import run_ice_setup

        if self.ellisys_path is None:
            raise SnifferError("EllisysBackend: analyzer path not set")
        await run_ice_setup(self.tcp_port, Path(self.ellisys_path))

    def _open_socket(self) -> None:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setblocking(False)
        self._sock = sock

    # ---------------------------------------------------------------- inject

    async def inject(self, h4_type, direction, payload, wall_clock):
        if self._sock is None:
            raise RuntimeError("EllisysBackend not started: call start() first")
        packet_type = ellisys_packet_type(h4_type, direction)
        pkt = encode_ellisys_injection_packet(
            wall_clock=wall_clock,
            bit_rate=self.bit_rate,
            packet_type=packet_type,
            hci_payload=payload,
            controller_index=self.controller_index,
        )
        try:
            self._sock.sendto(pkt, (self.host, self.udp_port))
        except OSError:
            logger.warning("EllisysBackend.inject: UDP sendto failed", exc_info=True)

    # ------------------------------------------------------------------ stop

    async def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
