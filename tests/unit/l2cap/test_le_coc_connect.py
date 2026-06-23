"""L2CAPManager.connect_le_coc_channel — outgoing LE CoC connection flow."""
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
    hci = MagicMock()
    hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    # Replace the LE signaling fixed channel's send with an AsyncMock so we can
    # intercept what's emitted and simulate the peer's response.
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    return m, sig_ch


async def _drive_response(manager, *, handle, ident, resp: LECreditBasedConnectionResponse):
    """Helper: feed a Connect Response PDU into the dispatcher to resolve a future."""
    pdu = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident, resp.encode(),
    )
    await manager._on_le_signaling(handle=handle, data=pdu)


@pytest.mark.asyncio
async def test_connect_le_coc_sends_request_and_returns_channel(manager_with_le_conn):
    m, sig_ch = manager_with_le_conn

    async def connect_coro():
        return await m.connect_le_coc_channel(
            handle=0x000C, psm=0x0080,
            mtu=512, mps=247, initial_credits=10, timeout=2.0,
        )

    connect_task = asyncio.create_task(connect_coro())
    # Allow the connect to send its request first.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Inspect the outgoing request.
    sig_ch.send.assert_called()
    sent_pdu = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent_pdu)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST
    assert isinstance(payload, LECreditBasedConnectionRequest)
    assert payload.le_psm == 0x0080
    assert payload.scid == 0x0040    # first allocation
    assert payload.mtu == 512
    assert payload.mps == 247
    assert payload.initial_credits == 10

    # Simulate the peer's Connect Response.
    await _drive_response(m, handle=0x000C, ident=ident,
                          resp=LECreditBasedConnectionResponse(
                              dcid=0x0050, mtu=247, mps=247,
                              initial_credits=5, result=0x0000,
                          ))
    ch = await connect_task
    assert isinstance(ch, LECoCChannel)
    assert ch.cid == 0x0040
    assert ch._peer_cid == 0x0050
    # MTU/MPS negotiated to the minimum of ours and theirs.
    assert ch.mtu == min(512, 247)
    # Channel is now registered both in the per-handle dict and _le_channels.
    assert m._le_channels[0x0040] is ch
    assert m._connections[0x000C][0x0040] is ch


@pytest.mark.asyncio
async def test_connect_le_coc_failed_result_raises(manager_with_le_conn):
    m, sig_ch = manager_with_le_conn
    connect_task = asyncio.create_task(m.connect_le_coc_channel(
        handle=0x000C, psm=0x00FF, timeout=2.0,
    ))
    await asyncio.sleep(0); await asyncio.sleep(0)
    sent_pdu = sig_ch.send.await_args.args[0]
    code, ident, _ = decode_le_signaling(sent_pdu)
    # Simulate "PSM not supported" (0x0002).
    await _drive_response(m, handle=0x000C, ident=ident,
                          resp=LECreditBasedConnectionResponse(
                              dcid=0, mtu=0, mps=0, initial_credits=0, result=0x0002,
                          ))
    with pytest.raises(RuntimeError, match="0x0002"):
        await connect_task
    # No channel registered after failure.
    assert m._le_channels == {}


@pytest.mark.asyncio
async def test_connect_le_coc_unknown_handle_raises():
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    with pytest.raises(RuntimeError, match="no.*connection"):
        await m.connect_le_coc_channel(handle=0xDEAD, psm=0x0080)


@pytest.mark.asyncio
async def test_connect_le_coc_timeout_cleans_up_pending(manager_with_le_conn):
    m, _ = manager_with_le_conn
    with pytest.raises(asyncio.TimeoutError):
        await m.connect_le_coc_channel(handle=0x000C, psm=0x0080, timeout=0.05)
    assert m._pending_le_connect == {}
