import pytest

from pybluehost.sniffer.ellisys import EllisysBackend


def test_ellisys_backend_defaults():
    b = EllisysBackend()
    assert b.host == "127.0.0.1"
    assert b.udp_port == 24352
    assert b.tcp_port == 46148
    assert b.skip_launch is False


def test_ellisys_backend_overrides():
    b = EllisysBackend(host="192.168.0.5", udp_port=24400, tcp_port=46200, skip_launch=True)
    assert b.host == "192.168.0.5"
    assert b.udp_port == 24400
    assert b.tcp_port == 46200
    assert b.skip_launch is True


import asyncio
import socket as _socket
from datetime import datetime, timezone

from pybluehost.core.trace import Direction
from pybluehost.sniffer.ellisys import EllisysBackend, encode_ellisys_injection_packet


async def test_ellisys_backend_injects_over_udp():
    """skip_launch=True → only _open_socket runs; inject() sends UDP; mock server receives."""
    # Bind a UDP socket on an OS-chosen port to act as the analyzer.
    server = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(2.0)
    _, port = server.getsockname()

    backend = EllisysBackend(
        host="127.0.0.1", udp_port=port, skip_launch=True,
        controller_index=0, bit_rate=12_000_000.0,
    )
    await backend.start()
    try:
        wall = datetime(2026, 1, 15, 0, 0, 1, 0, tzinfo=timezone.utc)
        hci_payload = bytes.fromhex("03 0C 00")  # HCI Reset (no H4)
        await backend.inject(
            h4_type=0x01, direction=Direction.DOWN,
            payload=hci_payload, wall_clock=wall,
        )
        # Give the UDP loopback a beat
        await asyncio.sleep(0.01)
        data, _src = server.recvfrom(4096)
    finally:
        await backend.stop()
        server.close()

    # The received bytes must exactly equal what encode_ellisys_injection_packet produces
    # for packet_type=0x01 (Command, from §3.2 mapping of H4=0x01 + DOWN).
    expected = encode_ellisys_injection_packet(
        wall_clock=wall, bit_rate=12_000_000.0,
        packet_type=0x01, hci_payload=hci_payload, controller_index=0,
    )
    assert data == expected


async def test_ellisys_backend_inject_before_start_raises():
    backend = EllisysBackend(skip_launch=True)
    with pytest.raises(RuntimeError, match="not started"):
        await backend.inject(
            h4_type=0x01, direction=Direction.DOWN,
            payload=b"\x00", wall_clock=datetime.now(timezone.utc),
        )
