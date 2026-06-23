"""L2CAPManager.listen_le_coc_channel + incoming LE CoC connection handling."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.types import LinkType
from pybluehost.l2cap.ble import LECoCChannel
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
    decode_le_signaling, encode_le_signaling,
)
from pybluehost.l2cap.manager import L2CAPManager


@pytest.fixture
async def manager_with_le_conn():
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    return m, sig_ch


async def _drive_request(m, *, handle, ident, req):
    pdu = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, ident, req.encode(),
    )
    await m._on_le_signaling(handle=handle, data=pdu)


@pytest.mark.asyncio
async def test_listen_registers_handler():
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    handler = MagicMock()
    m.listen_le_coc_channel(psm=0x0080, handler=handler)
    assert m._le_listeners[0x0080] is handler


@pytest.mark.asyncio
async def test_incoming_with_no_listener_returns_psm_not_supported(manager_with_le_conn):
    m, sig_ch = manager_with_le_conn
    req = LECreditBasedConnectionRequest(
        le_psm=0x0099, scid=0x0050, mtu=247, mps=247, initial_credits=5,
    )
    await _drive_request(m, handle=0x000C, ident=0x10, req=req)
    # Response written to signaling channel.
    sig_ch.send.assert_awaited_once()
    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE
    assert ident == 0x10
    assert isinstance(payload, LECreditBasedConnectionResponse)
    assert payload.result == 0x0002    # PSM not supported
    # No channel created.
    assert m._le_channels == {}


@pytest.mark.asyncio
async def test_incoming_with_listener_creates_channel_and_calls_handler(manager_with_le_conn):
    m, sig_ch = manager_with_le_conn
    delivered = {}
    def handler(ch):
        delivered["channel"] = ch
    m.listen_le_coc_channel(psm=0x0080, handler=handler)

    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=247, mps=247, initial_credits=5,
    )
    await _drive_request(m, handle=0x000C, ident=0x11, req=req)

    # Response sent with result=SUCCESS, our dcid allocated.
    sig_ch.send.assert_awaited_once()
    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE
    assert payload.result == 0x0000
    assert payload.dcid == 0x0040    # first allocation in this session

    # Channel created and registered.
    ch = delivered["channel"]
    assert isinstance(ch, LECoCChannel)
    assert ch.cid == 0x0040
    assert ch._peer_cid == 0x0060
    assert m._le_channels[0x0040] is ch
    assert m._connections[0x000C][0x0040] is ch


@pytest.mark.asyncio
async def test_incoming_with_async_handler_is_awaited(manager_with_le_conn):
    m, _ = manager_with_le_conn
    awaited = {"flag": False}
    async def async_handler(ch):
        awaited["flag"] = True
    m.listen_le_coc_channel(psm=0x0080, handler=async_handler)

    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0061, mtu=247, mps=247, initial_credits=5,
    )
    await _drive_request(m, handle=0x000C, ident=0x12, req=req)
    # Async handler is dispatched; await briefly so the task can run.
    await asyncio.sleep(0)
    assert awaited["flag"] is True
