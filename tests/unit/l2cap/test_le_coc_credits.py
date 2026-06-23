"""LE CoC credit & disconnect — credits already routed in T2; T5 adds disconnect."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    DisconnectionRequest, DisconnectionResponse,
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LEFlowControlCredit,
    LE_SIG_DISCONNECTION_REQUEST,
    LE_SIG_DISCONNECTION_RESPONSE,
    LE_SIG_LE_FLOW_CONTROL_CREDIT,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
    decode_le_signaling, encode_le_signaling,
)
from pybluehost.l2cap.manager import L2CAPManager


@pytest.fixture
async def manager_with_open_channel():
    """Manager with one LE connection and one open LE CoC channel."""
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    # Open a channel via the listen path so we have a real LECoCChannel.
    delivered = {}
    def handler(ch):
        delivered["channel"] = ch
    m.listen_le_coc_channel(psm=0x0080, handler=handler)
    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=247, mps=247, initial_credits=5,
    )
    pdu = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x10, req.encode(),
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sig_ch.send.reset_mock()      # forget the connect response
    return m, sig_ch, delivered["channel"]


@pytest.mark.asyncio
async def test_credit_pdu_adds_credits_to_channel(manager_with_open_channel):
    m, _, ch = manager_with_open_channel
    # Before: 5 initial credits.
    initial = ch._tx_credits._value
    body = LEFlowControlCredit(cid=0x0060, credits=3).encode()    # peer's CID (== ch.peer_cid)
    pdu = encode_le_signaling(LE_SIG_LE_FLOW_CONTROL_CREDIT, 0x20, body)
    await m._on_le_signaling(handle=0x000C, data=pdu)
    assert ch._tx_credits._value == initial + 3


@pytest.mark.asyncio
async def test_disconnect_le_coc_channel_sends_request_and_cleans_up(manager_with_open_channel):
    m, sig_ch, ch = manager_with_open_channel
    local_cid = ch.cid
    peer_cid = ch._peer_cid

    await m.disconnect_le_coc_channel(ch)

    sig_ch.send.assert_called()
    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert isinstance(payload, DisconnectionRequest)
    assert payload.dcid == peer_cid         # destination = peer's CID
    assert payload.scid == local_cid        # source = our CID

    # Channel removed from manager state.
    assert local_cid not in m._le_channels
    assert local_cid not in m._connections[0x000C]


@pytest.mark.asyncio
async def test_inbound_disconnection_request_closes_channel_and_responds(manager_with_open_channel):
    m, sig_ch, ch = manager_with_open_channel
    local_cid = ch.cid
    peer_cid = ch._peer_cid

    # Peer requests disconnect: req.dcid = our local CID, req.scid = peer's CID.
    body = DisconnectionRequest(dcid=local_cid, scid=peer_cid).encode()
    pdu = encode_le_signaling(LE_SIG_DISCONNECTION_REQUEST, 0x21, body)
    await m._on_le_signaling(handle=0x000C, data=pdu)

    # We respond with DISCONNECTION_RESPONSE mirroring the cids.
    sig_ch.send.assert_called()
    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_RESPONSE
    assert ident == 0x21
    assert isinstance(payload, DisconnectionResponse)
    assert payload.dcid == local_cid
    assert payload.scid == peer_cid

    # Channel removed locally.
    assert local_cid not in m._le_channels


@pytest.mark.asyncio
async def test_inbound_disconnect_for_unknown_cid_replies_anyway(manager_with_open_channel):
    """Per Core Spec, peer's disconnect request should be acknowledged even if
    we don't know the CID — robust behaviour for stale state."""
    m, sig_ch, _ = manager_with_open_channel
    body = DisconnectionRequest(dcid=0x0099, scid=0x0066).encode()
    pdu = encode_le_signaling(LE_SIG_DISCONNECTION_REQUEST, 0x22, body)
    await m._on_le_signaling(handle=0x000C, data=pdu)
    # Even with unknown cid, we still send a response (Core Spec §4.7).
    sig_ch.send.assert_called()
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_RESPONSE
    assert payload.dcid == 0x0099
    assert payload.scid == 0x0066
