"""Tests for RFCOMM frame codec and session management."""
from __future__ import annotations

from pybluehost.classic.rfcomm import (
    RFCOMMChannel,
    RFCOMMFrame,
    RFCOMMFrameType,
    RFCOMMManager,
    RFCOMMSession,
    calc_fcs,
    decode_frame,
    encode_frame,
)
from pybluehost.l2cap.constants import PSM_RFCOMM


# ---------------------------------------------------------------------------
# Frame type enum
# ---------------------------------------------------------------------------

def test_rfcomm_frame_type_enum_completeness():
    """All standard RFCOMM frame types must be defined."""
    expected = {"SABM", "UA", "DM", "DISC", "UIH", "UI"}
    assert expected.issubset({t.name for t in RFCOMMFrameType})


# ---------------------------------------------------------------------------
# FCS
# ---------------------------------------------------------------------------

def test_fcs_calculation():
    fcs = calc_fcs(bytes([0x03, 0x2F, 0x01]))
    assert isinstance(fcs, int)
    assert 0 <= fcs <= 255


def test_fcs_different_inputs_differ():
    fcs1 = calc_fcs(bytes([0x03, 0x2F, 0x01]))
    fcs2 = calc_fcs(bytes([0x03, 0xEF, 0x01]))
    assert fcs1 != fcs2


# ---------------------------------------------------------------------------
# SABM
# ---------------------------------------------------------------------------

def test_sabm_frame_encode():
    frame = RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.SABM, pf=True, data=b"")
    raw = encode_frame(frame)
    assert raw[0] == 0x03  # address: DLCI=0, C/R=1, EA=1
    assert raw[1] == 0x3F  # SABM|PF control byte
    assert raw[2] == 0x01  # length: 0 bytes, EA=1
    assert len(raw) == 4   # addr + ctrl + len + fcs


def test_sabm_frame_decode():
    frame = RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.SABM, pf=True, data=b"")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.dlci == 0
    assert decoded.frame_type == RFCOMMFrameType.SABM
    assert decoded.pf is True


# ---------------------------------------------------------------------------
# UA
# ---------------------------------------------------------------------------

def test_ua_frame_encode_decode():
    frame = RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UA, pf=True, data=b"")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.UA
    assert decoded.dlci == 0
    assert decoded.pf is True


# ---------------------------------------------------------------------------
# DM
# ---------------------------------------------------------------------------

def test_dm_frame_encode_decode():
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.DM, pf=True, data=b"")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.DM
    assert decoded.dlci == 2


# ---------------------------------------------------------------------------
# DISC
# ---------------------------------------------------------------------------

def test_disc_frame_encode_decode():
    frame = RFCOMMFrame(dlci=4, frame_type=RFCOMMFrameType.DISC, pf=True, data=b"")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.DISC
    assert decoded.dlci == 4


# ---------------------------------------------------------------------------
# UIH (data frames)
# ---------------------------------------------------------------------------

def test_uih_frame_encode():
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello")
    raw = encode_frame(frame)
    # Control byte: UIH without PF = 0xEF
    assert raw[1] == 0xEF
    assert b"hello" in raw


def test_uih_frame_decode_data():
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.frame_type == RFCOMMFrameType.UIH
    assert decoded.data == b"hello"
    assert decoded.dlci == 2


def test_uih_frame_with_pf():
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=True, data=b"x")
    raw = encode_frame(frame)
    assert raw[1] == 0xFF  # UIH with PF
    decoded = decode_frame(raw)
    assert decoded.pf is True


def test_uih_long_data():
    """UIH with >127 bytes uses 2-byte length field."""
    data = bytes(range(256)) * 2  # 512 bytes
    frame = RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=data)
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.data == data


# ---------------------------------------------------------------------------
# DLCI encoding
# ---------------------------------------------------------------------------

def test_dlci_encoding_high():
    """DLCI values up to 61 should encode correctly in address byte."""
    frame = RFCOMMFrame(dlci=30, frame_type=RFCOMMFrameType.SABM, pf=True, data=b"")
    raw = encode_frame(frame)
    decoded = decode_frame(raw)
    assert decoded.dlci == 30


# ---------------------------------------------------------------------------
# Session/Channel/Manager existence
# ---------------------------------------------------------------------------

def test_rfcomm_session_construction():
    session = RFCOMMSession(l2cap_channel=None)
    assert session is not None


def test_rfcomm_channel_properties():
    ch = RFCOMMChannel(dlci=2, session=None, max_frame_size=127)
    assert ch.dlci == 2
    assert ch.server_channel == 1  # server_channel = dlci >> 1
    assert ch.max_frame_size == 127


async def test_rfcomm_channel_send_writes_uih_frames_to_l2cap():
    class FakeL2CAPChannel:
        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

    l2cap = FakeL2CAPChannel()
    session = RFCOMMSession(l2cap_channel=l2cap)
    ch = RFCOMMChannel(dlci=2, session=session, max_frame_size=3)

    await ch.send(b"hello")

    decoded = [decode_frame(raw) for raw in l2cap.sent]
    assert [frame.data for frame in decoded] == [b"hel", b"lo"]
    assert all(frame.frame_type == RFCOMMFrameType.UIH for frame in decoded)


async def test_rfcomm_listen_fails_loudly_until_classic_l2cap_psm_exists():
    mgr = RFCOMMManager(l2cap=None)
    import pytest

    with pytest.raises(NotImplementedError, match="Classic L2CAP PSM 0x0003"):
        await mgr.listen(server_channel=1, handler=lambda _ch: None)


def test_rfcomm_manager_construction():
    mgr = RFCOMMManager(l2cap=None)
    assert mgr is not None


async def test_rfcomm_manager_connect_opens_l2cap_session_and_dlc():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)
            frame = decode_frame(data)
            if frame.frame_type == RFCOMMFrameType.SABM:
                await self.events.on_data(
                    encode_frame(
                        RFCOMMFrame(
                            dlci=frame.dlci,
                            frame_type=RFCOMMFrameType.UA,
                            pf=True,
                            data=b"",
                        )
                    )
                )

    class FakeL2CAP:
        def __init__(self):
            self.channel = FakeL2CAPChannel()
            self.calls = []

        async def connect_classic_channel(self, handle, psm):
            self.calls.append((handle, psm))
            return self.channel

    l2cap = FakeL2CAP()
    mgr = RFCOMMManager(l2cap=l2cap)

    ch = await mgr.connect(acl_handle=0x0042, server_channel=3)

    assert l2cap.calls == [(0x0042, PSM_RFCOMM)]
    assert ch.server_channel == 3
    assert [decode_frame(raw).dlci for raw in l2cap.channel.sent] == [0, 6]


async def test_rfcomm_manager_listen_accepts_sabm_and_dispatches_uih():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    class FakeL2CAP:
        def __init__(self):
            self.handler = None

        def listen_classic_channel(self, psm, handler):
            assert psm == PSM_RFCOMM
            self.handler = handler

    l2cap = FakeL2CAP()
    mgr = RFCOMMManager(l2cap=l2cap)
    accepted = []
    received = []

    async def on_channel(channel):
        accepted.append(channel)
        channel.on_data(lambda data: received.append(data))

    await mgr.listen(server_channel=3, handler=on_channel)
    l2cap_channel = FakeL2CAPChannel()
    await l2cap.handler(l2cap_channel)

    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.SABM, pf=True, data=b""))
    )
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=6, frame_type=RFCOMMFrameType.SABM, pf=True, data=b""))
    )
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=6, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello"))
    )

    assert [decode_frame(raw).frame_type for raw in l2cap_channel.sent] == [
        RFCOMMFrameType.UA,
        RFCOMMFrameType.UA,
    ]
    assert len(accepted) == 1
    assert accepted[0].server_channel == 3
    assert received == [b"hello"]


async def test_rfcomm_session_responds_to_inbound_parameter_negotiation():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    RFCOMMSession(l2cap_channel=l2cap_channel)
    pn_command = bytes.fromhex("03 ef 15 83 11 02 f0 00 00 de 03 00 07 70")

    await l2cap_channel.events.on_data(pn_command)

    assert len(l2cap_channel.sent) == 1
    response = decode_frame(l2cap_channel.sent[0])
    assert response.dlci == 0
    assert response.frame_type == RFCOMMFrameType.UIH
    assert response.data == bytes.fromhex("81 11 02 f0 00 00 de 03 00 07")
