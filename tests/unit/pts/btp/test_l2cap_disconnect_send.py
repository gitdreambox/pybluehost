"""L2CAP BTP Disconnect (0x03) + Send Data (0x04) handlers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.l2cap import LeCoCService


class _FakeChannel:
    def __init__(self):
        self.send_log: list[bytes] = []
        self.send = AsyncMock(side_effect=lambda data: self.send_log.append(bytes(data)))
        self.initial_credits = 10


class _FakeL2CAPManager:
    def __init__(self):
        self.disconnect_calls: list = []
        self.grant_calls: list = []

    async def disconnect_le_coc_channel(self, ch):
        self.disconnect_calls.append(ch)

    async def grant_le_coc_credits(self, ch, credits):
        self.grant_calls.append((ch, credits))


class _FakeStack:
    def __init__(self):
        self.l2cap = _FakeL2CAPManager()


class _FakeActions:
    def __init__(self):
        self._stack = _FakeStack()


def _make_svc_with_channel(*, chan_id=1):
    actions = _FakeActions()
    ch = _FakeChannel()
    svc = LeCoCService(actions=actions, tester=MagicMock())
    svc._channels[chan_id] = ch
    return svc, actions, ch


@pytest.mark.asyncio
async def test_disconnect_calls_manager_and_removes_channel():
    svc, actions, ch = _make_svc_with_channel(chan_id=3)
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_DISCONNECT, controller_index=0, data=bytes([3]),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == b""
    assert actions._stack.l2cap.disconnect_calls == [ch]
    assert 3 not in svc._channels


@pytest.mark.asyncio
async def test_disconnect_unknown_chan_id_fails():
    svc, _, _ = _make_svc_with_channel(chan_id=1)
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_DISCONNECT, controller_index=0, data=bytes([99]),
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_disconnect_wrong_body_length_fails():
    svc, _, _ = _make_svc_with_channel()
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_DISCONNECT, controller_index=0, data=b"\x01\x02",
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_send_data_dispatches_to_channel():
    svc, _, ch = _make_svc_with_channel(chan_id=2)
    payload = b"\xAB\xCD\xEF\x01\x02"
    body = bytes([2]) + len(payload).to_bytes(2, "little") + payload
    status, resp = await svc.dispatch(
        opcode=op.OP_L2CAP_SEND_DATA, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert resp == b""
    assert ch.send_log == [payload]


@pytest.mark.asyncio
async def test_send_data_unknown_chan_id_fails():
    svc, _, _ = _make_svc_with_channel(chan_id=1)
    body = bytes([99]) + (1).to_bytes(2, "little") + b"\x00"
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_SEND_DATA, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_send_data_payload_length_mismatch_fails():
    """Header says 5 bytes but only 3 follow."""
    svc, _, _ = _make_svc_with_channel(chan_id=1)
    body = bytes([1]) + (5).to_bytes(2, "little") + b"\x01\x02\x03"
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_SEND_DATA, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_send_data_empty_payload_ok():
    svc, _, ch = _make_svc_with_channel(chan_id=1)
    body = bytes([1]) + (0).to_bytes(2, "little")
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_SEND_DATA, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert ch.send_log == [b""]


@pytest.mark.asyncio
async def test_credits_grants_initial_credits():
    """CREDITS (0x08): body chan_id(u8) → grant_le_coc_credits(ch, initial_credits)."""
    svc, actions, ch = _make_svc_with_channel(chan_id=2)
    status, data = await svc.dispatch(
        opcode=op.OP_L2CAP_CREDITS, controller_index=0, data=bytes([2]),
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert data == b""
    assert actions._stack.l2cap.grant_calls == [(ch, 10)]


@pytest.mark.asyncio
async def test_credits_unknown_chan_id_fails():
    svc, _, _ = _make_svc_with_channel(chan_id=1)
    status, _ = await svc.dispatch(
        opcode=op.OP_L2CAP_CREDITS, controller_index=0, data=bytes([9]),
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_reconfigured_event_tells_autopts_the_new_channel_sizes():
    """BTP L2CAP_EV_RECONFIGURED (0x84), body chan_id(u8) + peer_mtu(u16) +
    peer_mps(u16) + our_mtu(u16) + our_mps(u16). auto-pts's `l2cap.reconfigured`
    just stores these on the channel model — without the event it keeps grading
    later steps (the SDU sizes it asks for) against the pre-reconfigure values."""
    svc, actions, ch = _make_svc_with_channel(chan_id=2)
    emitted: list = []
    svc._emit_event = lambda opcode, payload: emitted.append((opcode, payload))

    ch._mtu = 512
    ch._mps = 247
    ch._rx_mtu = 65
    ch._rx_mps = 64
    svc._on_channel_reconfigured(ch)

    assert len(emitted) == 1
    opcode, payload = emitted[0]
    assert opcode == op.OP_L2CAP_EVENT_RECONFIGURED
    assert payload == (
        bytes([2])
        + (512).to_bytes(2, "little") + (247).to_bytes(2, "little")
        + (65).to_bytes(2, "little") + (64).to_bytes(2, "little")
    )


def test_reconfigured_event_ignores_channels_it_does_not_own():
    svc, actions, ch = _make_svc_with_channel(chan_id=1)
    emitted: list = []
    svc._emit_event = lambda opcode, payload: emitted.append(opcode)
    svc._on_channel_reconfigured(object())
    assert emitted == []
