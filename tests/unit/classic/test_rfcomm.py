"""Tests for RFCOMM frame codec and session management."""
from __future__ import annotations

import asyncio

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
            elif frame.frame_type == RFCOMMFrameType.UIH and frame.data \
                    and frame.data[0] == 0x83:  # MCC PN command
                # MCC PN command (initiator) — answer with a PN response
                # echoing the DLCI so the negotiation completes.
                from pybluehost.classic.rfcomm import _MCC_TYPE_PN_RESPONSE
                length_field = frame.data[1]
                body = frame.data[2:2 + (length_field >> 1)]
                await self.events.on_data(
                    encode_frame(
                        RFCOMMFrame(
                            dlci=0,
                            frame_type=RFCOMMFrameType.UIH,
                            pf=False,
                            data=bytes([_MCC_TYPE_PN_RESPONSE, length_field]) + body,
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
    # Frame order: SABM(0), PN(dlc), SABM(dlc)
    kinds = [(decode_frame(raw).dlci, decode_frame(raw).frame_type.name)
             for raw in l2cap.channel.sent]
    assert kinds == [(0, "SABM"), (0, "UIH"), (6, "SABM")]


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
    await asyncio.sleep(0)
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=6, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello"))
    )

    assert [decode_frame(raw).frame_type for raw in l2cap_channel.sent] == [
        RFCOMMFrameType.UA,
        RFCOMMFrameType.UA,
        RFCOMMFrameType.UIH,
    ]
    assert decode_frame(l2cap_channel.sent[2]).data == bytes.fromhex("e3 05 1b 8d")
    assert len(accepted) == 1
    assert accepted[0].server_channel == 3
    assert received == [b"hello"]


async def test_rfcomm_inbound_handler_does_not_block_future_frames():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    received = []

    async def on_channel(channel):
        channel.on_data(lambda data: received.append(data))
        await asyncio.Event().wait()

    RFCOMMSession(l2cap_channel=l2cap_channel, server_handlers={1: on_channel})

    await asyncio.wait_for(
        l2cap_channel.events.on_data(
            encode_frame(RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.SABM, pf=True, data=b""))
        ),
        timeout=0.1,
    )
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=2, frame_type=RFCOMMFrameType.UIH, pf=False, data=b"hello"))
    )

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
    # Request has flow=0xF0 (PN_CFC_CMD): we accept credit — response is
    # PN_CFC_RESP 0xE0, priority/ack/retrans 0, frame size min(peer's
    # 0x03DE, 127), K=7 credits issued to the peer (zephyr parity).
    assert response.data == bytes.fromhex("81 11 02 e0 00 00 7f 00 00 07")
    # Responder MCC responses clear the address C/R bit (0x01).
    assert l2cap_channel.sent[0][0] == 0x01


async def test_rfcomm_session_responds_to_inbound_modem_status_command():
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
    msc_command = encode_frame(
        RFCOMMFrame(
            dlci=0,
            frame_type=RFCOMMFrameType.UIH,
            pf=False,
            data=bytes.fromhex("e3 05 0b 8d"),
        )
    )

    await l2cap_channel.events.on_data(msc_command)

    assert len(l2cap_channel.sent) == 1
    response = decode_frame(l2cap_channel.sent[0])
    assert response.dlci == 0
    assert response.frame_type == RFCOMMFrameType.UIH
    assert response.data == bytes.fromhex("e1 05 0b 8d")


async def test_rfcomm_session_sends_rls_command():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    session = RFCOMMSession(l2cap_channel=l2cap_channel)

    await session.send_rls(10, 0x09)  # DLCI 10 (server channel 5), framing error

    assert len(l2cap_channel.sent) == 1
    frame = decode_frame(l2cap_channel.sent[0])
    assert frame.dlci == 0
    assert frame.frame_type == RFCOMMFrameType.UIH
    # RLS command type 0x53 (type 0x14<<2|CR|EA), len 2
    assert frame.data == bytes([0x53, 0x05, (10 << 2) | 0x03, 0x09])


async def test_rfcomm_session_sends_rpn_command():
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    session = RFCOMMSession(l2cap_channel=l2cap_channel)

    await session.send_rpn(10, baud_rate=7, line_settings=3, flow_control=0,
                           xon_char=0x11, xoff_char=0x13, param_mask=0x3FFF)

    assert len(l2cap_channel.sent) == 1
    frame = decode_frame(l2cap_channel.sent[0])
    assert frame.dlci == 0
    # RPN command type 0x93, len 8
    assert frame.data[:2] == bytes([0x93, 0x11])
    assert frame.data[2:] == bytes([(10 << 2) | 0x03, 7, 3, 0, 0x11, 0x13]) \
        + (0x3FFF).to_bytes(2, "little")


async def test_rfcomm_session_responds_to_inbound_rls_and_rpn():
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

    rls_command = encode_frame(
        RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False,
                    data=bytes([0x53, 0x05, 0x2B, 0x09])))
    await l2cap_channel.events.on_data(rls_command)
    rpn_command = encode_frame(
        RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False,
                    data=bytes([0x93, 0x11, 0x2B, 7, 3, 0, 0x11, 0x13, 0xFF, 0x3F])))
    await l2cap_channel.events.on_data(rpn_command)

    assert len(l2cap_channel.sent) == 2
    rls_rsp = decode_frame(l2cap_channel.sent[0])
    assert rls_rsp.data == bytes([0x51, 0x05, 0x2B, 0x09])  # echoed, response type
    rpn_rsp = decode_frame(l2cap_channel.sent[1])
    assert rpn_rsp.data == bytes([0x91, 0x11, 0x2B, 7, 3, 0, 0x11, 0x13,
                                  0xFF, 0x3F])


async def test_rfcomm_session_answers_unknown_mcc_with_nsc():
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

    # FCON (Flow Control On, type 0x28<<2|CR|EA = 0xA3? no — use 0x63: an
    # arbitrary unsupported command type byte).
    unknown = encode_frame(
        RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False,
                    data=bytes([0x63, 0x03, 0x01])))
    await l2cap_channel.events.on_data(unknown)

    assert len(l2cap_channel.sent) == 1
    frame = decode_frame(l2cap_channel.sent[0])
    assert frame.dlci == 0
    # NSC response type 0x11, len 1, payload = offending command type
    assert frame.data == bytes([0x11, 0x03, 0x63])


async def test_rfcomm_session_answers_rpn_value_request_with_current_settings():
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

    # RPN with only the DLCI byte = request for current port values (BV-19).
    rpn_request = encode_frame(
        RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False,
                    data=bytes([0x93, 0x03, 0x2B])))
    await l2cap_channel.events.on_data(rpn_request)

    assert len(l2cap_channel.sent) == 1
    rsp = decode_frame(l2cap_channel.sent[0])
    assert rsp.data[0] == 0x91  # RPN response type
    assert rsp.data[1] == 0x11  # length field: 8 payload bytes
    assert rsp.data[2] == 0x2B  # DLCI echoed
    assert len(rsp.data[3:]) == 7  # baud+line+flow+xon+xoff+mask(2)
    mask = int.from_bytes(rsp.data[-2:], "little")
    assert mask & 0x0100 == 0  # reserved bit 8 clear


async def test_rfcomm_credit_negotiation_and_send_accounting():
    """8-byte PN with flow=0xF0 (credit proposal) → 0xE0+K response;
    sends stop at 0 credits and resume on a credit-issuing UIH (BV-21/22)."""
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    received = []

    async def on_channel(channel):
        channel.on_data(lambda data: received.append(data))

    session = RFCOMMSession(l2cap_channel=l2cap_channel,
                            server_handlers={5: on_channel})

    # PTS's PN for DLCI 10 with credit flow byte 0xF0 (PN_CFC_CMD) + K=2
    # credits in body byte 8 (zephyr bt_rfcomm_pn layout: credits is the
    # last of the 8 body bytes, not a 9th).
    pn = encode_frame(
        RFCOMMFrame(dlci=0, frame_type=RFCOMMFrameType.UIH, pf=False,
                    data=bytes([0x83, 0x11, 10, 0xF0, 0x01, 0x00, 0x7F, 0x00,
                                0x00, 0x02])))
    await l2cap_channel.events.on_data(pn)
    pn_rsp = decode_frame(l2cap_channel.sent[-1])
    assert pn_rsp.data[0] == 0x81
    assert pn_rsp.data[2] == 10 and pn_rsp.data[3] == 0xE0  # PN_CFC_RESP
    assert pn_rsp.data[-1] == 0x07  # our K=7 credits issued to the peer

    # SABM for the DLC → channel inherits the 2 peer-issued credits.
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=10, frame_type=RFCOMMFrameType.SABM,
                                 pf=True, data=b"")))
    await asyncio.sleep(0)
    channel = session._dlcs[10]
    assert channel._tx_credits == 2

    # 3 frames' worth of data: send() returns immediately (queue model),
    # the drainer emits exactly the credited 2, then stops.
    await channel.send(b"a" * (127 * 2 + 1))
    await asyncio.sleep(0.1)
    data_frames = [decode_frame(raw) for raw in l2cap_channel.sent
                   if decode_frame(raw).dlci == 10
                   and decode_frame(raw).frame_type == RFCOMMFrameType.UIH]
    assert len(data_frames) == 2  # exactly the credited count, then stop

    # Peer issues 1 more credit via P/F=1 UIH → the 3rd frame goes out.
    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=10, frame_type=RFCOMMFrameType.UIH,
                                 pf=True, data=bytes([0x01]))))
    await asyncio.sleep(0.1)
    data_frames = [decode_frame(raw) for raw in l2cap_channel.sent
                   if decode_frame(raw).dlci == 10
                   and decode_frame(raw).frame_type == RFCOMMFrameType.UIH]
    assert len(data_frames) == 3


async def test_rfcomm_acceptor_session_data_frames_use_cr_clear():
    """zephyr BT_RFCOMM_UIH_CR: data UIH from a session ACCEPTOR carries
    C/R=0 in the address byte; from the initiator, C/R=1."""
    class FakeL2CAPChannel:
        def __init__(self):
            self.events = None
            self.sent = []

        def set_events(self, events):
            self.events = events

        async def send(self, data):
            self.sent.append(data)

    l2cap_channel = FakeL2CAPChannel()
    session = RFCOMMSession(l2cap_channel=l2cap_channel,
                            server_handlers={5: lambda ch: None})
    assert session._initiator is False  # acceptor (no open())

    await l2cap_channel.events.on_data(
        encode_frame(RFCOMMFrame(dlci=10, frame_type=RFCOMMFrameType.SABM,
                                 pf=True, data=b"")))
    await asyncio.sleep(0)
    channel = session._dlcs[10]
    await channel.send(b"hello")
    data_frame = l2cap_channel.sent[-1]
    assert data_frame[0] == (10 << 2) | 0x01  # EA=1, C/R=0, DLCI=10

    # And an acceptor-originated DISC also carries C/R=0.
    await channel.close()
    disc = l2cap_channel.sent[-1]
    assert disc[0] == (10 << 2) | 0x01
