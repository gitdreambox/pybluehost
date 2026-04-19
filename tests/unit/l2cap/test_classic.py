"""Tests for Classic L2CAP channels: ClassicChannel, ERTMEngine, StreamingEngine."""
import asyncio
import struct

import pytest

from pybluehost.l2cap.channel import ChannelState
from pybluehost.l2cap.classic import (
    ChannelMode,
    ClassicChannel,
    ERTMEngine,
    StreamingEngine,
)


class FakeHCI:
    def __init__(self) -> None:
        self.sent: list[tuple[int, int, bytes]] = []

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        self.sent.append((handle, pb_flag, data))


def test_channel_mode_enum() -> None:
    assert ChannelMode.BASIC == 0x00
    assert ChannelMode.ERTM == 0x03
    assert ChannelMode.STREAMING == 0x04


async def test_classic_channel_basic_send() -> None:
    hci = FakeHCI()
    ch = ClassicChannel(
        connection_handle=0x0001,
        local_cid=0x0040,
        peer_cid=0x0041,
        mode=ChannelMode.BASIC,
        hci=hci,
    )
    ch.open()
    await ch.send(b"hello")
    assert len(hci.sent) == 1
    handle, pb_flag, data = hci.sent[0]
    assert handle == 0x0001
    length, cid = struct.unpack_from("<HH", data)
    assert length == 5
    assert cid == 0x0041  # peer CID
    assert data[4:] == b"hello"


async def test_classic_channel_not_open_raises() -> None:
    hci = FakeHCI()
    ch = ClassicChannel(
        connection_handle=0x0001,
        local_cid=0x0040,
        peer_cid=0x0041,
        mode=ChannelMode.BASIC,
        hci=hci,
    )
    with pytest.raises(RuntimeError, match="not open"):
        await ch.send(b"data")


async def test_ertm_engine_sends_iframe() -> None:
    engine = ERTMEngine(tx_window=4)
    frames: list[bytes] = []

    async def send_fn(data: bytes) -> None:
        frames.append(data)

    engine.set_send_fn(send_fn)
    await engine.send_sdu(b"hello")
    assert len(frames) == 1
    assert frames[0][0] & 0x01 == 0  # I-frame (bit 0 = 0)
    sdu_len = struct.unpack_from("<H", frames[0], 2)[0]
    assert sdu_len == 5
    assert frames[0][4:] == b"hello"


async def test_ertm_engine_acks_release_window() -> None:
    engine = ERTMEngine(tx_window=2)
    frames: list[bytes] = []

    async def send_fn(data: bytes) -> None:
        frames.append(data)

    engine.set_send_fn(send_fn)
    await engine.send_sdu(b"pkt1")
    await engine.send_sdu(b"pkt2")
    # Window exhausted -- third send blocks until ACK
    engine.on_sframe(req_seq=1)  # ACK seq=0
    await asyncio.wait_for(engine.send_sdu(b"pkt3"), timeout=0.5)
    assert len(frames) == 3


def test_ertm_on_iframe_returns_rr_sframe() -> None:
    engine = ERTMEngine(tx_window=4)
    sframe = engine.on_iframe(tx_seq=0, data=b"x")
    assert sframe[0] & 0x01 == 0x01  # S-frame marker
    assert (sframe[0] >> 2) & 0x3F == 1  # req_seq=1


async def test_streaming_engine_sends_no_ack() -> None:
    """Streaming mode sends I-frames without expecting ACK."""
    engine = StreamingEngine()
    frames: list[bytes] = []

    async def send_fn(data: bytes) -> None:
        frames.append(data)

    engine.set_send_fn(send_fn)
    await engine.send_sdu(b"stream1")
    await engine.send_sdu(b"stream2")
    assert len(frames) == 2
    # Verify sequence numbers increment
    assert (frames[0][0] >> 1) == 0  # tx_seq=0
    assert (frames[1][0] >> 1) == 1  # tx_seq=1


async def test_classic_channel_ertm_send() -> None:
    hci = FakeHCI()
    ch = ClassicChannel(
        connection_handle=0x0001,
        local_cid=0x0040,
        peer_cid=0x0041,
        mode=ChannelMode.ERTM,
        hci=hci,
    )
    ch.open()
    await ch.send(b"ertm-data")
    assert len(hci.sent) == 1
