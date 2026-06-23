"""L2CAPManager LE signaling dispatcher — routes 0x06/0x07/0x14/0x15/0x16 PDUs."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LEFlowControlCredit, DisconnectionRequest,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
    LE_SIG_LE_FLOW_CONTROL_CREDIT,
    LE_SIG_DISCONNECTION_REQUEST,
    encode_le_signaling,
)
from pybluehost.l2cap.manager import L2CAPManager


def _make_manager() -> L2CAPManager:
    hci = MagicMock()
    hci.send_acl_data = AsyncMock()
    return L2CAPManager(hci=hci)


def test_manager_init_adds_le_state():
    m = _make_manager()
    assert m._le_listeners == {}
    assert m._pending_le_connect == {}
    assert m._next_le_signaling_id == 1
    # LE dynamic CID range per Core Spec Vol 3 Part A §2.1 starts at 0x0040.
    assert m._next_le_cid == 0x0040
    assert m._le_channels == {}


def test_allocate_le_cid_increments():
    m = _make_manager()
    a = m._allocate_le_cid()
    b = m._allocate_le_cid()
    assert a == 0x0040
    assert b == 0x0041
    assert m._next_le_cid == 0x0042


def test_next_le_signaling_id_wraps_after_0xFF():
    m = _make_manager()
    m._next_le_signaling_id = 0xFF
    assert m._next_le_signaling_id_value() == 0xFF
    # After consume, wraps to 1 (not 0 — 0 reserved).
    assert m._next_le_signaling_id_value() == 0x01


@pytest.mark.asyncio
async def test_on_connection_wires_le_signaling_handler():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    # Events bound: on_data callback should be set to dispatch into _on_le_signaling.
    assert sig_ch._events is not None
    assert sig_ch._events.on_data is not None


@pytest.mark.asyncio
async def test_le_signaling_response_resolves_pending_future():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    fut = asyncio.get_event_loop().create_future()
    m._pending_le_connect[0x05] = fut

    body = LECreditBasedConnectionResponse(
        dcid=0x0050, mtu=247, mps=247, initial_credits=5, result=0x0000,
    ).encode()
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, 0x05, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    assert fut.done()
    resp = fut.result()
    assert resp.dcid == 0x0050
    assert resp.result == 0x0000
    assert 0x05 not in m._pending_le_connect


@pytest.mark.asyncio
async def test_le_signaling_credit_pdu_dispatches_to_channel():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    # Register a fake channel whose _peer_cid matches the credit PDU's cid.
    fake_channel = MagicMock()
    fake_channel._peer_cid = 0x0060
    fake_channel.add_credits = MagicMock()
    m._le_channels[0x0042] = fake_channel

    body = LEFlowControlCredit(cid=0x0060, credits=7).encode()
    pdu = encode_le_signaling(LE_SIG_LE_FLOW_CONTROL_CREDIT, 0x06, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    fake_channel.add_credits.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_le_signaling_request_routed_to_incoming_handler(monkeypatch):
    """Incoming LE_CREDIT_BASED_CONNECTION_REQUEST is dispatched to
    `_handle_incoming_le_coc_request`. T2 makes this a no-op stub so this test
    just confirms the dispatcher routes — T4 will replace the stub."""
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    called = {}
    async def fake_handler(handle, ident, req):
        called["args"] = (handle, ident, req)
    monkeypatch.setattr(m, "_handle_incoming_le_coc_request", fake_handler)

    body = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0040, mtu=512, mps=251, initial_credits=10,
    ).encode()
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x07, body)

    await m._on_le_signaling(handle=0x000C, data=pdu)

    assert called["args"][0] == 0x000C
    assert called["args"][1] == 0x07
    assert called["args"][2].le_psm == 0x0080


@pytest.mark.asyncio
async def test_send_le_signaling_writes_to_signaling_channel():
    m = _make_manager()
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    await m._send_le_signaling(
        handle=0x000C, code=LE_SIG_LE_FLOW_CONTROL_CREDIT, ident=0x08,
        payload=LEFlowControlCredit(cid=0x0040, credits=3).encode(),
    )

    sig_ch.send.assert_awaited_once()
    sent = sig_ch.send.await_args.args[0]
    # First byte = code, second = ident.
    assert sent[0] == LE_SIG_LE_FLOW_CONTROL_CREDIT
    assert sent[1] == 0x08
