"""Tests for install_att_channel_mux — GATT client+server sharing one ATT channel.

PTS GAP/SEC cases have the IUT act as both GATT server (PTS reads a protected
characteristic) and GATT client (WID ops toward PTS) on the SAME ATT fixed
channel. The channel has a single ``on_data`` callback; before the mux, the
client bearer's ``set_events`` replaced the server handler, so the server
stopped answering and PTS disconnected (GAP/SEC/AUT INDCSV). The mux routes
each inbound PDU by opcode so both roles coexist.
"""
from __future__ import annotations

import pytest

from pybluehost.l2cap.ble import FixedChannel
from pybluehost.l2cap.channel import install_att_channel_mux
from pybluehost.l2cap.constants import CID_ATT


class _Hci:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send_acl_data(self, handle, pb, payload):
        self.sent.append(payload)


def _channel() -> FixedChannel:
    return FixedChannel(connection_handle=0x0800, cid=CID_ATT, hci=_Hci(), mtu=23)


@pytest.mark.asyncio
async def test_mux_routes_request_to_server_and_response_to_client():
    ch = _channel()
    install_att_channel_mux(ch)
    server_got: list[bytes] = []
    client_got: list[bytes] = []
    ch._att_server_handler = lambda d: server_got.append(d)
    ch._att_client_handler = lambda d: client_got.append(d)

    # Read Request (0x0A) is a client->server request -> server.
    await ch._on_pdu(bytes([0x0A, 0x03, 0x00]))
    # Read Response (0x0B) is a server->client response -> client.
    await ch._on_pdu(bytes([0x0B, 0xAA]))

    assert server_got == [bytes([0x0A, 0x03, 0x00])]
    assert client_got == [bytes([0x0B, 0xAA])]


@pytest.mark.asyncio
async def test_mux_server_survives_client_attach():
    """The BV-12 scenario: client bearer attaches after the server bound, and
    the server must STILL answer PTS's read of a protected characteristic."""
    ch = _channel()
    install_att_channel_mux(ch)
    server_got: list[bytes] = []
    ch._att_server_handler = lambda d: server_got.append(d)

    # A client bearer attaches later (overwrites nothing under the mux).
    install_att_channel_mux(ch)
    client_got: list[bytes] = []
    ch._att_client_handler = lambda d: client_got.append(d)

    await ch._on_pdu(bytes([0x0A, 0x03, 0x00]))  # PTS Read Request
    assert server_got == [bytes([0x0A, 0x03, 0x00])]
    assert client_got == []


@pytest.mark.asyncio
async def test_mux_drops_response_when_no_client_handler():
    """Pure-server (GATT/SR): a stray response must be dropped, not answered."""
    ch = _channel()
    install_att_channel_mux(ch)
    server_got: list[bytes] = []
    ch._att_server_handler = lambda d: server_got.append(d)

    await ch._on_pdu(bytes([0x0B, 0xAA]))  # Read Response with no client
    assert server_got == []  # not routed to the server


@pytest.mark.asyncio
async def test_mux_is_idempotent_and_supports_async_handlers():
    ch = _channel()
    install_att_channel_mux(ch)
    install_att_channel_mux(ch)  # second install is a no-op
    got: list[bytes] = []

    async def _async_server(d: bytes) -> None:
        got.append(d)

    ch._att_server_handler = _async_server
    await ch._on_pdu(bytes([0x12, 0x05, 0x00, 0x01]))  # Write Request
    assert got == [bytes([0x12, 0x05, 0x00, 0x01])]


@pytest.mark.asyncio
async def test_mux_routes_confirmation_to_confirmation_handler():
    """The Service Changed confirmation (0x1E) must reach the server's
    confirmation hook (which clears change-unaware) when one is registered, in
    preference to the client bearer (which just drops it)."""
    ch = _channel()
    install_att_channel_mux(ch)
    client_got: list[bytes] = []
    confirmed: list[bytes] = []
    ch._att_client_handler = lambda d: client_got.append(d)
    ch._att_confirmation_handler = lambda d: confirmed.append(d)

    await ch._on_pdu(bytes([0x1E]))

    assert confirmed == [bytes([0x1E])]
    assert client_got == []


@pytest.mark.asyncio
async def test_mux_confirmation_falls_back_to_client_when_no_confirmation_hook():
    """Without a confirmation hook the 0x1E still goes to the client bearer as
    before — the pure-server case has neither and just drops it."""
    ch = _channel()
    install_att_channel_mux(ch)
    client_got: list[bytes] = []
    ch._att_client_handler = lambda d: client_got.append(d)

    await ch._on_pdu(bytes([0x1E]))

    assert client_got == [bytes([0x1E])]


@pytest.mark.asyncio
async def test_mux_routes_all_request_opcodes_to_server():
    ch = _channel()
    install_att_channel_mux(ch)
    server_got: list[bytes] = []
    client_got: list[bytes] = []
    ch._att_server_handler = lambda d: server_got.append(d)
    ch._att_client_handler = lambda d: client_got.append(d)

    # Write Command (0x52) and Signed Write (0xD2) are server-bound too.
    await ch._on_pdu(bytes([0x52, 0x01, 0x00, 0xFF]))
    await ch._on_pdu(bytes([0xD2]) + bytes(13))
    # Read Multiple (0x0E) and Read Multiple Variable Length (0x20) are
    # client→server requests — PTS GAR/BV-11 sends 0x20 over an EATT bearer,
    # and dropping it there hangs the case until time_guard.
    await ch._on_pdu(bytes([0x0E, 0x01, 0x00, 0x02, 0x00]))
    await ch._on_pdu(bytes([0x20, 0x01, 0x00, 0x02, 0x00]))
    # Notification (0x1B) and Confirmation (0x1E) are client-bound.
    await ch._on_pdu(bytes([0x1B, 0x01, 0x00, 0x01]))
    await ch._on_pdu(bytes([0x1E]))

    assert [d[0] for d in server_got] == [0x52, 0xD2, 0x0E, 0x20]
    assert [d[0] for d in client_got] == [0x1B, 0x1E]
