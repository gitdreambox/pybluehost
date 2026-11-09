"""L2CAP BTP Listen (0x05) handler + events 0x81/0x82/0x83."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.l2cap import LeCoCService


class _FakeChannel:
    def __init__(self, *, cid=0x0040, peer_cid=0x0050, mtu=247, mps=247):
        self.cid = cid
        self._peer_cid = peer_cid
        self.mtu = mtu
        self._mps = mps
        self._events = None

    def set_events(self, events):
        self._events = events


class _FakeL2CAPManager:
    def __init__(self):
        self.listen_calls: list = []

    def listen_le_coc_channel(self, psm, handler, required_security=0):
        self.listen_calls.append((psm, handler, required_security))


class _FakeStack:
    def __init__(self):
        self.l2cap = _FakeL2CAPManager()


class _FakeActions:
    def __init__(self):
        self._stack = _FakeStack()


class _FakeTester:
    def __init__(self):
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame):
        self.events.append(frame)


def _make_svc():
    return LeCoCService(actions=_FakeActions(), tester=_FakeTester()), \
           _FakeActions  # tester is svc._tester after this


@pytest.mark.asyncio
async def test_listen_registers_with_stack_manager():
    actions = _FakeActions()
    tester = _FakeTester()
    svc = LeCoCService(actions=actions, tester=tester)
    # Body >= 9 bytes: PSM(2) + Transport(1) + MTU(2) + Security(1) + Key_Size(1) + Response(2)
    body = (
        (0x0080).to_bytes(2, "little")    # PSM
        + bytes([0])                       # Transport (LE)
        + (512).to_bytes(2, "little")      # MTU
        + bytes([0, 16])                   # Security_Type, Key_Size
        + (0).to_bytes(2, "little")        # Response
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == b""
    # Listener registered.
    assert len(actions._stack.l2cap.listen_calls) == 1
    psm, handler, required_security = actions._stack.l2cap.listen_calls[0]
    assert psm == 0x0080
    assert callable(handler)
    assert required_security == 0


@pytest.mark.asyncio
async def test_listen_short_body_fails():
    actions = _FakeActions()
    svc = LeCoCService(actions=actions, tester=MagicMock())
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=b"\x00\x01",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_listen_accepts_seven_byte_autopts_body():
    """auto-pts master ``l2cap_listen`` packs only 7 octets (PSM+Transport+MTU+
    Response) — it predates the spec's Security_Type/Key_Size fields. The handler
    must accept the 7-octet form, not just the 9-octet spec form."""
    actions = _FakeActions()
    svc = LeCoCService(actions=actions, tester=MagicMock())
    body = (
        (0x0080).to_bytes(2, "little")    # PSM
        + bytes([0])                       # Transport (LE)
        + (512).to_bytes(2, "little")      # MTU
        + (0).to_bytes(2, "little")        # Response (success)
    )
    assert len(body) == 7
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    psm, handler, required_security = actions._stack.l2cap.listen_calls[0]
    assert psm == 0x0080
    assert required_security == 0


@pytest.mark.asyncio
async def test_listen_passes_security_response_to_manager():
    """The LISTEN Response field (offset 5) must reach the manager as
    required_security so the listener enforces it (PTS security-responder cases
    L2CAP/LE/CFC/BV-11/13/15/25)."""
    actions = _FakeActions()
    svc = LeCoCService(actions=actions, tester=MagicMock())
    body = (
        (0x0080).to_bytes(2, "little")    # PSM
        + bytes([0])                       # Transport (LE)
        + (512).to_bytes(2, "little")      # MTU
        + (1).to_bytes(2, "little")        # Response = insufficient_authentication
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    psm, handler, required_security = actions._stack.l2cap.listen_calls[0]
    assert psm == 0x0080
    assert required_security == 1


@pytest.mark.asyncio
async def test_listen_v2_registers_listener_with_response_security():
    """LISTEN_V2 (0x0c) — auto-pts l2cap_listen_v2 packs PSM(2)+Transport(1)+
    MTU(2)+Response(2)+Mode(1)+Options(4). The Response must reach the manager
    as required_security (ECFC listener setup)."""
    actions = _FakeActions()
    svc = LeCoCService(actions=actions, tester=MagicMock())
    body = (
        (0x0080).to_bytes(2, "little")    # PSM
        + bytes([0])                       # Transport (LE)
        + (512).to_bytes(2, "little")      # MTU
        + (4).to_bytes(2, "little")        # Response = insufficient_encryption
        + bytes([0])                       # Mode (basic)
        + (0).to_bytes(4, "little")        # Options
    )
    assert len(body) == 12
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_LISTEN_V2, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    psm, handler, required_security = actions._stack.l2cap.listen_calls[0]
    assert psm == 0x0080
    assert required_security == 4


@pytest.mark.asyncio
async def test_incoming_channel_emits_connected_event_and_stores_channel():
    """When the registered handler is invoked with a channel, emit 0x81."""
    actions = _FakeActions()
    tester = _FakeTester()
    svc = LeCoCService(actions=actions, tester=tester)
    body = (
        (0x0080).to_bytes(2, "little") + bytes([0]) + (512).to_bytes(2, "little")
        + bytes([0, 16]) + (0).to_bytes(2, "little")
    )
    await svc.dispatch(opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body)
    handler = actions._stack.l2cap.listen_calls[0][1]

    fake_ch = _FakeChannel(cid=0x0040, peer_cid=0x0050, mtu=247, mps=247)
    handler(fake_ch)
    await asyncio.sleep(0)

    # Channel stored under a BTP chan_id (u8).
    assert len(svc._channels) == 1
    btp_chan_id = next(iter(svc._channels))
    assert svc._channels[btp_chan_id] is fake_ch

    # 0x81 Connected event emitted.
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.service == op.SERVICE_L2CAP
    assert evt.opcode == op.OP_L2CAP_EVENT_CONNECTED
    # Payload: chan_id(1) + psm(2) + peer_mtu(2) + peer_mps(2) + our_mtu(2) + our_mps(2) + addr_type(1) + addr(6) = 18 bytes
    assert len(evt.data) == 18
    assert evt.data[0] == btp_chan_id
    assert int.from_bytes(evt.data[1:3], "little") == 0x0080


@pytest.mark.asyncio
async def test_incoming_channel_routes_data_to_event():
    actions = _FakeActions()
    tester = _FakeTester()
    svc = LeCoCService(actions=actions, tester=tester)
    body = (
        (0x0080).to_bytes(2, "little") + bytes([0]) + (512).to_bytes(2, "little")
        + bytes([0, 16]) + (0).to_bytes(2, "little")
    )
    await svc.dispatch(opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body)
    handler = actions._stack.l2cap.listen_calls[0][1]

    fake_ch = _FakeChannel()
    handler(fake_ch)
    btp_chan_id = next(iter(svc._channels))

    # Trigger the bound on_data callback by directly invoking it.
    assert fake_ch._events is not None
    on_data = fake_ch._events.on_data
    assert on_data is not None
    result = on_data(b"\xAA\xBB\xCC")
    if asyncio.iscoroutine(result):
        await result
    await asyncio.sleep(0)

    # First event was Connected; second is Data Received.
    data_events = [e for e in tester.events if e.opcode == op.OP_L2CAP_EVENT_DATA_RECEIVED]
    assert len(data_events) == 1
    evt = data_events[0]
    assert evt.data[0] == btp_chan_id
    assert int.from_bytes(evt.data[1:3], "little") == 3
    assert evt.data[3:6] == b"\xAA\xBB\xCC"


@pytest.mark.asyncio
async def test_incoming_channel_emits_disconnected_on_close():
    actions = _FakeActions()
    tester = _FakeTester()
    svc = LeCoCService(actions=actions, tester=tester)
    body = (
        (0x0080).to_bytes(2, "little") + bytes([0]) + (512).to_bytes(2, "little")
        + bytes([0, 16]) + (0).to_bytes(2, "little")
    )
    await svc.dispatch(opcode=op.OP_L2CAP_LISTEN, controller_index=0, data=body)
    handler = actions._stack.l2cap.listen_calls[0][1]

    fake_ch = _FakeChannel()
    handler(fake_ch)
    btp_chan_id = next(iter(svc._channels))

    on_close = fake_ch._events.on_close
    assert on_close is not None
    result = on_close(0x13)  # reason byte from HCI disconnect
    if asyncio.iscoroutine(result):
        await result
    await asyncio.sleep(0)

    disc_events = [e for e in tester.events if e.opcode == op.OP_L2CAP_EVENT_DISCONNECTED]
    assert len(disc_events) == 1
    evt = disc_events[0]
    # Payload: result(u16) + chan_id(1) + psm(u16) + addr_type(1) + addr(6) = 12 bytes
    assert len(evt.data) == 12
    assert evt.data[2] == btp_chan_id
    assert int.from_bytes(evt.data[3:5], "little") == 0x0080
    # Channel removed from registry.
    assert btp_chan_id not in svc._channels
