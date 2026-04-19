"""Tests for BLE L2CAP channels: FixedChannel and LECoCChannel."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.l2cap.ble import FixedChannel, LECoCChannel
from pybluehost.l2cap.channel import ChannelState, SimpleChannelEvents


class FakeHCI:
    def __init__(self) -> None:
        self.sent: list[tuple[int, int, bytes]] = []

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        self.sent.append((handle, pb_flag, data))


# ---------------------------------------------------------------------------
# FixedChannel
# ---------------------------------------------------------------------------


async def test_fixed_channel_send():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci, mtu=23)
    await ch.send(b"\x01\x02\x03")
    assert len(hci.sent) == 1
    handle, pb_flag, data = hci.sent[0]
    assert handle == 0x0040
    length, cid = struct.unpack_from("<HH", data)
    assert length == 3
    assert cid == 0x0004
    assert data[4:] == b"\x01\x02\x03"


async def test_fixed_channel_receive():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci, mtu=23)
    received: list[bytes] = []

    async def on_data(data: bytes) -> None:
        received.append(data)

    ch.set_events(SimpleChannelEvents(on_data=on_data))
    await ch._on_pdu(b"\xDE\xAD")
    assert received == [b"\xDE\xAD"]


def test_fixed_channel_state():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci)
    assert ch.state == ChannelState.OPEN
    assert ch.cid == 0x0004
    assert ch.connection_handle == 0x0040


async def test_fixed_channel_close():
    hci = FakeHCI()
    ch = FixedChannel(connection_handle=0x0040, cid=0x0004, hci=hci)
    assert ch.state == ChannelState.OPEN
    await ch.close()
    assert ch.state == ChannelState.CLOSED


# ---------------------------------------------------------------------------
# LECoCChannel
# ---------------------------------------------------------------------------


async def test_le_coc_channel_send_single_segment():
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
        mtu=512,
        mps=247,
        initial_credits=10,
    )
    await ch.send(b"hello")
    assert len(hci.sent) == 1
    handle, pb_flag, data = hci.sent[0]
    assert handle == 0x0040
    # L2CAP header: length(2) + peer_cid(2) + SDU_length(2) + payload
    l2cap_len, cid = struct.unpack_from("<HH", data)
    assert cid == 0x0041  # peer CID
    # SDU length field (first segment only)
    sdu_len = struct.unpack_from("<H", data, 4)[0]
    assert sdu_len == 5
    assert data[6:] == b"hello"


async def test_le_coc_channel_receive():
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
        mtu=512,
        mps=247,
        initial_credits=10,
    )
    received: list[bytes] = []

    async def on_data(data: bytes) -> None:
        received.append(data)

    ch.set_events(SimpleChannelEvents(on_data=on_data))
    # Simulate receiving a single-segment SDU: SDU length (2 bytes) + payload
    sdu_data = struct.pack("<H", 5) + b"world"
    await ch._on_pdu(sdu_data)
    assert received == [b"world"]


async def test_le_coc_credit_exhaustion():
    """When credits are exhausted, send should block until credits added."""
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
        mtu=512,
        mps=247,
        initial_credits=1,
    )
    await ch.send(b"first")  # uses the 1 credit
    assert len(hci.sent) == 1

    # Next send should block
    send_task = asyncio.ensure_future(ch.send(b"second"))
    await asyncio.sleep(0.05)
    assert not send_task.done()  # blocked

    # Add credit
    ch.add_credits(1)
    await asyncio.wait_for(send_task, timeout=0.5)
    assert len(hci.sent) == 2


async def test_le_coc_channel_close():
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
    )
    assert ch.state == ChannelState.OPEN
    await ch.close()
    assert ch.state == ChannelState.DISCONNECTING


async def test_le_coc_multi_segment_receive():
    """Reassembly across multiple PDUs."""
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
        mtu=512,
        mps=5,  # small MPS to force segmentation
        initial_credits=10,
    )
    received: list[bytes] = []

    async def on_data(data: bytes) -> None:
        received.append(data)

    ch.set_events(SimpleChannelEvents(on_data=on_data))

    payload = b"ABCDEFGH"  # 8 bytes
    # First segment: SDU length (2 bytes) + first chunk of payload
    first_seg = struct.pack("<H", len(payload)) + payload[:3]  # 2+3 = 5 bytes
    await ch._on_pdu(first_seg)
    assert received == []  # not yet complete

    # Second segment: next chunk
    await ch._on_pdu(payload[3:8])
    assert received == [b"ABCDEFGH"]


async def test_le_coc_multi_segment_send():
    """Send an SDU larger than MPS; should produce multiple segments."""
    hci = FakeHCI()
    ch = LECoCChannel(
        connection_handle=0x0040,
        local_cid=0x0040,
        peer_cid=0x0041,
        hci=hci,
        mtu=512,
        mps=5,  # very small MPS
        initial_credits=10,
    )
    payload = b"ABCDEFGH"  # 8 bytes; with 2-byte SDU len = 10 bytes total
    await ch.send(payload)
    # 10 bytes / 5 MPS = 2 segments
    assert len(hci.sent) == 2

    # First segment should contain SDU length + start of payload
    _, _, seg0 = hci.sent[0]
    seg0_payload = seg0[4:]  # strip L2CAP header
    sdu_len = struct.unpack_from("<H", seg0_payload)[0]
    assert sdu_len == 8

    # Reassemble all segment payloads (strip L2CAP headers)
    all_payload = b""
    for _, _, seg in hci.sent:
        all_payload += seg[4:]
    # First 2 bytes are SDU length, rest is the original payload
    assert all_payload[2:] == payload
