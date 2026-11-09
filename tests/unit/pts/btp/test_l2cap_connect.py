"""L2CAP BTP Connect handler (0x02) — upstream-aligned wire format."""
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import asyncio

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.l2cap import LeCoCService


# ---- Fakes --------------------------------------------------------------
#
# The peer is a real BDAddress: ``.address`` is big-endian display order and
# ``to_hci()`` is the little-endian HCI wire order. auto-pts sends the CONNECT
# address little-endian (``addr_str_to_le_bytes``), so the wire body uses
# ``to_hci()`` while the stored peer keeps display order — this locks the
# byte-order regression that made every real L2CAP connect return BTP_ERROR.

@dataclass
class _FakeChannel:
    cid: int = 0x0040
    _peer_cid: int = 0x0050
    mtu: int = 512
    _mps: int = 247
    _rx_mtu: int = 512
    _rx_mps: int = 247
    events: object = None

    def set_events(self, events):
        self.events = events


@dataclass
class _ConnInfo:
    handle: int
    peer: BDAddress
    transport: str = "le"


@dataclass
class _FakeSession:
    connections: dict


class _FakeL2CAPManager:
    def __init__(self):
        self.connect_calls = []
        self.connect_many_calls = []
        self.next_channel = _FakeChannel()

    async def connect_le_coc_channel(self, *, handle, psm, mtu=512, mps=247,
                                      initial_credits=10, timeout=5.0):
        self.connect_calls.append(
            {"handle": handle, "psm": psm, "mtu": mtu, "mps": mps,
             "initial_credits": initial_credits, "timeout": timeout}
        )
        return self.next_channel

    async def connect_le_coc_channels(self, *, handle, psm, mtu=512, mps=247,
                                       initial_credits=10, num=1, timeout=5.0):
        self.connect_many_calls.append(
            {"handle": handle, "psm": psm, "num": num, "mtu": mtu}
        )
        return [_FakeChannel(cid=0x0040 + i) for i in range(num)]


class _FakeStack:
    def __init__(self):
        self.l2cap = _FakeL2CAPManager()


class _FakeActions:
    def __init__(self, conns=None):
        self._stack = _FakeStack()
        self._session = _FakeSession(connections=conns or {})

    def status(self):
        return self._session


def _peer(display="AA:BB:CC:DD:EE:FF") -> BDAddress:
    return BDAddress.from_string(display)


def _make_svc_with_peer(display="AA:BB:CC:DD:EE:FF", conn_handle=0x000C):
    peer = _peer(display)
    actions = _FakeActions(conns={
        conn_handle: _ConnInfo(handle=conn_handle, peer=peer),
    })
    tester = MagicMock()
    tester.emit_event = AsyncMock()   # _emit_event wraps it in asyncio.create_task
    return LeCoCService(actions=actions, tester=tester), actions, peer


@pytest.mark.asyncio
async def test_connect_returns_chan_id_and_records_channel():
    svc, actions, peer = _make_svc_with_peer()
    body = (
        bytes([op.GAP_ADDR_TYPE_RANDOM]) + peer.to_hci()
        + (0x0080).to_bytes(2, "little")    # PSM
        + (512).to_bytes(2, "little")        # MTU
        + bytes([1])                         # Num
        + bytes([0])                         # Options (unused in P.8 v1)
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Response: Num(u8) + chan_ids(u8 × Num)
    assert data[0] == 1
    chan_id = data[1]
    assert chan_id == 0   # first allocation (auto-pts addresses chan 0)
    # Service records the channel.
    assert chan_id in svc._channels
    # connect_le_coc_channel was called with the right args.
    call = actions._stack.l2cap.connect_calls[0]
    assert call["handle"] == 0x000C
    assert call["psm"] == 0x0080
    assert call["mtu"] == 512


@pytest.mark.asyncio
async def test_connect_tolerates_a_response_delayed_beyond_100ms():
    """The controller can receive PTS's valid response in 16 ms while the
    Windows/USB host delivers it to asyncio after the 100 ms BTP-only window.
    The normal CONNECT path must retain the manager's 1 s RTX budget instead
    of abandoning the pending future before that response is dispatched."""
    svc, actions, peer = _make_svc_with_peer()

    async def delayed_connect(**kwargs):
        async def answer():
            await asyncio.sleep(0.2)
            return actions._stack.l2cap.next_channel

        return await asyncio.wait_for(answer(), timeout=kwargs["timeout"])

    actions._stack.l2cap.connect_le_coc_channel = delayed_connect
    body = (
        bytes([0]) + peer.to_hci()
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )

    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )

    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1


@pytest.mark.asyncio
async def test_connect_emits_connected_event():
    """Outgoing CONNECT must emit BTP_L2CAP_EV_CONNECTED (0x81) with the chan_id
    so the autopts stack model (l2cap.connected) marks the channel up — without
    it, later data/confirm WIDs time out and PTS returns INCONC."""
    svc, actions, peer = _make_svc_with_peer()
    tester = svc._tester
    body = (
        bytes([0]) + peer.to_hci()
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    chan_id = data[1]
    # Let the create_task'd emit_event run.
    import asyncio
    await asyncio.sleep(0)
    assert tester.emit_event.await_count == 1
    frame = tester.emit_event.await_args.args[0]
    assert frame.opcode == op.OP_L2CAP_EVENT_CONNECTED
    assert frame.data[0] == chan_id
    assert int.from_bytes(frame.data[1:3], "little") == 0x0080  # psm


@pytest.mark.asyncio
async def test_connect_wire_address_is_little_endian():
    """Regression: the BTP CONNECT address arrives little-endian; it must match
    the peer's ``to_hci()`` form, not the big-endian display ``.address``. A
    palindromic-free address proves the handler didn't compare display order."""
    # Display 5C:67:83:07:04:EE → to_hci() = EE 04 07 83 67 5C (distinct from BE).
    svc, actions, peer = _make_svc_with_peer("5C:67:83:07:04:EE")
    assert peer.to_hci() == bytes.fromhex("EE040783675C")
    body = (
        bytes([0]) + peer.to_hci()
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert actions._stack.l2cap.connect_calls[0]["handle"] == 0x000C


@pytest.mark.asyncio
async def test_connect_short_body_fails():
    svc, _, peer = _make_svc_with_peer()
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=b"\x00\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_unknown_peer_fails():
    """Body addr doesn't match any active LE connection → FAILED."""
    svc, _, _ = _make_svc_with_peer("AA:BB:CC:DD:EE:FF")
    body = (
        bytes([0]) + bytes.fromhex("000000000000")
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connect_multi_channel_uses_ecfc_and_returns_all_ids():
    """Num > 1 must use the Enhanced Credit-Based path (connect_le_coc_channels)
    and answer num + one chan_id per channel — the ECFC initiator contract
    (PTS L2CAP/ECFC/*)."""
    svc, actions, peer = _make_svc_with_peer()
    body = (
        bytes([0]) + peer.to_hci() + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little")
        + bytes([3, 0])   # Num=3
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 3                          # num channels connected
    assert len(data) == 4                        # num + 3 chan_ids
    chan_ids = list(data[1:])
    for chan_id in chan_ids:
        assert chan_id in svc._channels
    call = actions._stack.l2cap.connect_many_calls[0]
    assert call["num"] == 3
    assert call["psm"] == 0x0080


@pytest.mark.asyncio
async def test_connect_manager_raises_returns_failed():
    svc, actions, peer = _make_svc_with_peer()
    async def boom(**kwargs):
        raise RuntimeError("LE CoC connect failed: result=0x0002")
    actions._stack.l2cap.connect_le_coc_channel = boom
    body = (
        bytes([0]) + peer.to_hci() + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little") + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
    # No channel registered after failure.
    assert svc._channels == {}


@pytest.mark.asyncio
async def test_connect_refused_reports_pending_channel_and_disconnected_event():
    """A peer REFUSAL (LECoCConnectError — non-zero result / Command Reject) is
    an expected protocol outcome, so the BTP status stays SUCCESS — but per
    btp_l2cap.txt op 0x02 the response carries the chan_ids CREATED ("to allow
    cancellation of this connection request using Disconnect") and a Connected
    — or, in case of an error, DISCONNECTED — event follows. auto-pts's
    hdl_wid_280 (BI-29 connect rounds) indexes chans[0] right after
    l2cap_conn(), so num=0 crashes the WID; the 0x82 carries the refusal's
    L2CAP result code."""
    import struct as _struct

    from pybluehost.core.errors import LECoCConnectError
    svc, actions, peer = _make_svc_with_peer()
    async def refused(**kwargs):
        raise LECoCConnectError("refused", result=0x0008)   # insufficient encryption
    actions._stack.l2cap.connect_le_coc_channel = refused
    body = (
        bytes([0]) + peer.to_hci() + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little") + bytes([1, 0])
    )
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1                       # num=1 — one pending channel
    chan_id = data[1]
    assert svc._channels == {}                # nothing registered — never existed
    # The 0x82 is deliberately delayed so the chan reaches the stack model
    # (l2cap.connect(chans)) before the event flips it to DISCONNECTED.
    await asyncio.sleep(0.15)
    assert svc._tester.emit_event.await_count == 1
    frame = svc._tester.emit_event.await_args.args[0]
    assert frame.opcode == op.OP_L2CAP_EVENT_DISCONNECTED
    result, ev_chan, psm, _addr_type, _addr = _struct.unpack_from(
        "<HBHB6s", frame.data)
    assert (result, ev_chan, psm) == (0x0008, chan_id, 0x0080)


@pytest.mark.asyncio
async def test_connect_v2_refused_reports_pending_channel_and_event():
    import struct as _struct

    from pybluehost.core.errors import LECoCConnectError
    svc, actions, peer = _make_svc_with_peer()
    async def refused(**kwargs):
        raise LECoCConnectError("refused", result=0x0002)   # PSM not supported
    actions._stack.l2cap.connect_le_coc_channel = refused
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT_V2, controller_index=0,
        data=_connect_v2_body(peer.to_hci()),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1
    chan_id = data[1]
    await asyncio.sleep(0.15)
    frame = svc._tester.emit_event.await_args.args[0]
    assert frame.opcode == op.OP_L2CAP_EVENT_DISCONNECTED
    result, ev_chan, _psm, _t, _a = _struct.unpack_from("<HBHB6s", frame.data)
    assert (result, ev_chan) == (0x0002, chan_id)


@pytest.mark.asyncio
async def test_refusal_result_is_sanitized_for_the_wire():
    """auto-pts's l2cap_disconnected_ev does L2CapChannelStatusCode(res) — a
    result outside its map (e.g. the manager's Command-Reject sentinel −1)
    raises KeyError inside the event dispatch and the event is lost. Clamp
    unknown codes to 0x0004 (insufficient resources — a map member)."""
    import struct as _struct

    from pybluehost.core.errors import LECoCConnectError
    svc, actions, peer = _make_svc_with_peer()
    async def refused(**kwargs):
        raise LECoCConnectError("command rejected",
                                result=LECoCConnectError.RESULT_COMMAND_REJECT)
    actions._stack.l2cap.connect_le_coc_channel = refused
    body = (
        bytes([0]) + peer.to_hci() + (0x0080).to_bytes(2, "little")
        + (512).to_bytes(2, "little") + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    await asyncio.sleep(0.15)
    frame = svc._tester.emit_event.await_args.args[0]
    result = _struct.unpack_from("<H", frame.data)[0]
    assert result == 0x0004


# ---- CONNECT_V2 (0x0b) -----------------------------------------------------


def _connect_v2_body(wire_addr, psm=0x0080, mtu=512, num=1, mode=0, options=0):
    return (
        bytes([op.GAP_ADDR_TYPE_RANDOM]) + wire_addr
        + psm.to_bytes(2, "little")
        + mtu.to_bytes(2, "little")
        + bytes([num])
        + bytes([mode])
        + options.to_bytes(4, "little")
    )


@pytest.mark.asyncio
async def test_connect_v2_returns_chan_id_and_records_channel():
    """CONNECT_V2 (0x0b) carries an extra Mode(u8) + Options(u32) tail."""
    svc, actions, peer = _make_svc_with_peer()
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT_V2, controller_index=0,
        data=_connect_v2_body(peer.to_hci()),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data[0] == 1
    chan_id = data[1]
    assert chan_id in svc._channels
    call = actions._stack.l2cap.connect_calls[0]
    assert call["handle"] == 0x000C
    assert call["psm"] == 0x0080


@pytest.mark.asyncio
async def test_connect_v2_short_body_fails():
    svc, _, peer = _make_svc_with_peer()
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT_V2, controller_index=0,
        data=_connect_v2_body(peer.to_hci())[:-4],  # drop the Options tail → 13 bytes
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_connected_event_reports_our_advertised_mtu_mps():
    """our_mtu/our_mps in the 0x81 event must be OUR advertised receive limits
    (``_rx_mtu``/``_rx_mps`` — what the peer may send us), not copies of the
    peer-facing values. auto-pts grades received-SDU sizes against
    ``chan.our_mtu`` (WID 261) and sends ``chan.peer_mtu``-sized SDUs
    (WID 257/258); duplicating the peer values left the model unable to tell
    the two directions apart, which the MTU-renegotiation cases need."""
    svc, actions, peer = _make_svc_with_peer()
    actions._stack.l2cap.next_channel = _FakeChannel(
        mtu=64, _mps=64, _rx_mtu=512, _rx_mps=247)
    body = (
        bytes([0]) + peer.to_hci()
        + (0x0080).to_bytes(2, "little") + (512).to_bytes(2, "little")
        + bytes([1, 0])
    )
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CONNECT, controller_index=0, data=body,
    )
    import asyncio
    await asyncio.sleep(0)
    frame = svc._tester.emit_event.await_args.args[0]
    data = frame.data
    # layout: chan_id(1) psm(2) peer_mtu(2) peer_mps(2) our_mtu(2) our_mps(2)
    assert int.from_bytes(data[3:5], "little") == 64    # peer_mtu = channel mtu
    assert int.from_bytes(data[5:7], "little") == 64    # peer_mps
    assert int.from_bytes(data[7:9], "little") == 512   # our_mtu = our advertised
    assert int.from_bytes(data[9:11], "little") == 247  # our_mps = our advertised
