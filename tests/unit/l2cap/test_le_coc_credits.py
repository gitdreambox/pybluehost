"""LE CoC credit & disconnect — credits already routed in T2; T5 adds disconnect."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.types import LinkType
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.hci.packets import HCIACLData
from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    DisconnectionRequest, DisconnectionResponse,
    LECreditBasedConnectionRequest, LECreditBasedConnectionResponse,
    LEFlowControlCredit,
    LE_SIG_COMMAND_REJECT,
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
async def test_credit_overflow_disconnects_channel(manager_with_open_channel):
    """L2CAP/LE/CFC/BI-01: the credit counter is 16-bit (Core Spec Vol 3 Part A
    §4.24). A Flow Control Credit that would push the total above 65535 is a
    protocol violation — the IUT must disconnect the LE Data Channel."""
    from pybluehost.l2cap.le_signaling import LE_SIG_DISCONNECTION_REQUEST

    m, sig_ch, ch = manager_with_open_channel
    local_cid = ch.cid

    # Channel starts at 5 credits; a grant of 65535 overflows (5 + 65535 > 65535).
    body = LEFlowControlCredit(cid=ch._peer_cid, credits=65535).encode()
    pdu = encode_le_signaling(LE_SIG_LE_FLOW_CONTROL_CREDIT, 0x21, body)
    await m._on_le_signaling(handle=0x000C, data=pdu)

    codes = [c.args[0][0] for c in sig_ch.send.await_args_list]
    assert LE_SIG_DISCONNECTION_REQUEST in codes
    assert local_cid not in m._le_channels


@pytest.mark.asyncio
async def test_credit_exactly_at_ceiling_is_accepted(manager_with_open_channel):
    """A grant landing exactly on 65535 is legal (the ceiling is inclusive)."""
    m, sig_ch, ch = manager_with_open_channel
    from pybluehost.l2cap.le_signaling import LE_SIG_DISCONNECTION_REQUEST

    ch._tx_credits = asyncio.Semaphore(0)
    ch._tx_credits_total = 0
    body = LEFlowControlCredit(cid=ch._peer_cid, credits=65535).encode()
    pdu = encode_le_signaling(LE_SIG_LE_FLOW_CONTROL_CREDIT, 0x22, body)
    await m._on_le_signaling(handle=0x000C, data=pdu)

    codes = [c.args[0][0] for c in sig_ch.send.await_args_list]
    assert LE_SIG_DISCONNECTION_REQUEST not in codes


@pytest.mark.asyncio
async def test_received_kframe_grants_credit_back(manager_with_open_channel):
    """Receiving a K-frame must return an LE Flow Control Credit to the peer —
    the auto-grant that keeps the peer's send-credit pool from draining (PTS
    L2CAP/LE/CFC credit-exchange cases stall without it)."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    # Feed one K-frame: first segment = SDU_len(2) + 3 payload bytes.
    await ch._on_pdu((3).to_bytes(2, "little") + b"abc")
    sig_ch.send.assert_called()
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_LE_FLOW_CONTROL_CREDIT
    assert isinstance(payload, LEFlowControlCredit)
    assert payload.cid == ch.cid          # credit references OUR local CID
    assert payload.credits == 1           # one credit per consumed K-frame


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


# ---- K-frame protocol violations → IUT-initiated disconnect (PTS BV-26/27/28)


@pytest.mark.asyncio
async def test_kframe_sdu_length_over_mtu_triggers_disconnect(manager_with_open_channel):
    """BV-26: first K-frame's SDU Length field > channel MTU → IUT must send
    L2CAP_DISCONNECTION_REQ (0x06) for that channel."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    ch._rx_mtu = 23      # shrink receive limit for an easy violation
    # First segment: SDU length prefix says 100 (> MTU 23).
    await ch._on_pdu((100).to_bytes(2, "little") + b"abc")
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert payload.dcid == ch._peer_cid
    assert payload.scid == ch.cid
    # Channel torn down locally.
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_kframe_segment_payload_over_mps_triggers_disconnect(manager_with_open_channel):
    """BV-27: a K-frame whose Information Payload length > channel MPS → IUT
    sends L2CAP_DISCONNECTION_REQ."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    ch._rx_mps = 10      # shrink receive limit for an easy violation
    # Continuation segment of 20 bytes with no SDU reassembly pending yet is a
    # first-K-frame: len(SDU_len + payload) = 22 > MPS 10.
    await ch._on_pdu(b"\x10\x00" + b"x" * 20)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST


@pytest.mark.asyncio
async def test_kframe_segments_exceed_declared_sdu_length_disconnects(manager_with_open_channel):
    """BV-28: accumulated continuation segments exceed the SDU length declared
    in the first K-frame → IUT sends L2CAP_DISCONNECTION_REQ."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    # First K-frame: SDU length = 3.
    await ch._on_pdu((3).to_bytes(2, "little") + b"abc")
    # Continuation adds 4 more bytes → 7 > 3 declared.
    sig_ch.send.reset_mock()
    await ch._on_pdu(b"defg")
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_wellformed_multisegment_sdu_still_delivered(manager_with_open_channel):
    """Guard: the violation checks must not reject a legal segmented SDU."""
    m, sig_ch, ch = manager_with_open_channel
    got = []
    ch.set_events(SimpleChannelEvents(on_data=lambda d: got.append(d)))
    ch._rx_mtu = 100; ch._rx_mps = 10
    # SDU of 12 bytes in 3-byte first segment + 9-byte continuation.
    await ch._on_pdu((12).to_bytes(2, "little") + b"abc")
    assert got == []                     # not complete yet
    await ch._on_pdu(b"defghijkl")
    assert got == [b"abcdefghijkl"]


# ---- First-fragment violation fast-path (PTS BV-26/27 send only fragment 0) --


def _first_fragment_pkt(handle, cid, declared_len, payload):
    """Build a FIRST ACL fragment carrying an L2CAP header + partial payload."""
    l2cap = declared_len.to_bytes(2, "little") + cid.to_bytes(2, "little") + payload
    return HCIACLData(handle=handle, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=l2cap)


@pytest.mark.asyncio
async def test_first_fragment_payload_over_mps_disconnects_before_reassembly(
        manager_with_open_channel):
    """BV-27: PTS sends only the FIRST ACL fragment of an oversized K-frame
    (declared L2CAP length > our advertised MPS) then waits ~300 s for the IUT
    to disconnect. SAR reassembly never completes, so the violation must be
    caught on the first fragment — matching the on-air capture (declared len
    259 > advertised MPS 247, only 3 payload bytes sent)."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    assert ch._rx_mps == 247
    pkt = _first_fragment_pkt(0x000C, ch.cid, declared_len=259,
                              payload=(257).to_bytes(2, "little") + b"\x00")
    await m.on_acl_data(pkt)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert payload.dcid == ch._peer_cid
    assert payload.scid == ch.cid
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_first_fragment_sdu_length_over_mtu_disconnects_before_reassembly(
        manager_with_open_channel):
    """BV-26: SDU-length prefix > our advertised MTU, declared on a legal-sized
    first K-frame (declared length <= MPS). Caught on the first fragment."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    assert ch._rx_mtu == 512
    pkt = _first_fragment_pkt(0x000C, ch.cid, declared_len=10,
                              payload=(600).to_bytes(2, "little") + b"abcdefgh")
    await m.on_acl_data(pkt)
    sent = sig_ch.send.await_args.args[0]
    code, _, _ = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_first_fragment_legal_frame_no_false_positive(manager_with_open_channel):
    """Guard: a legal first fragment (declared length <= MPS, SDU length <= MTU)
    must NOT trigger the violation path — normal reassembly/delivery proceeds."""
    m, sig_ch, ch = manager_with_open_channel
    got = []
    ch.set_events(SimpleChannelEvents(on_data=lambda d: got.append(d)))
    # Complete 6-byte SDU in a single fragment: declared length 8 = 2 + 6.
    pkt = _first_fragment_pkt(0x000C, ch.cid, declared_len=8,
                              payload=(6).to_bytes(2, "little") + b"abcdef")
    await m.on_acl_data(pkt)
    assert got == [b"abcdef"]           # delivered normally
    assert ch.cid in m._le_channels     # channel NOT torn down


@pytest.mark.asyncio
async def test_first_fragment_full_mps_k_frame_is_legal_not_a_violation(
        manager_with_open_channel):
    """A K-frame whose Information Payload is EXACTLY our advertised MPS is
    legal (Core Vol 3 Part A §3.4.2: on a first K-frame the L2CAP length field
    counts the 2-byte SDU-length prefix, so declared = payload + 2). Comparing
    declared_len raw against the MPS flagged every full-size frame and tore the
    channel down — PTS L2CAP/COS/ECFC/BV-04-C (Reassembling, MTU = MPS) sends
    precisely these and died on its first K-frame (INDCSV ×3, 0x18 out → 0x13)."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    got = []
    ch.set_events(SimpleChannelEvents(on_data=lambda d: got.append(d)))
    sdu = bytes(range(247))
    # declared = SDU-length prefix (2) + payload (247) = 249 > rx_mps 247 — legal.
    pkt = _first_fragment_pkt(0x000C, ch.cid, declared_len=249,
                              payload=(247).to_bytes(2, "little") + sdu)
    await m.on_acl_data(pkt)
    assert got == [sdu]                 # delivered normally
    assert ch.cid in m._le_channels     # channel NOT torn down
    # No teardown signaling — a credit grant-back (0x16) is fine, a
    # DISCONNECTION_REQUEST (0x06) is not.
    for call_args in sig_ch.send.await_args_list:
        assert call_args.args[0][0] != 0x06, "channel was torn down"


@pytest.mark.asyncio
async def test_first_fragment_payload_one_over_mps_still_disconnects(
        manager_with_open_channel):
    """BV-27 boundary with the SDU-prefix adjustment: Information Payload
    MPS+1 (declared = MPS + 3) on a first K-frame is still a violation."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    pkt = _first_fragment_pkt(0x000C, ch.cid, declared_len=250,
                              payload=(248).to_bytes(2, "little")
                              + bytes(246))
    await m.on_acl_data(pkt)
    sent = sig_ch.send.await_args.args[0]
    code, _, _ = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_REQUEST
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_first_fragment_violation_skipped_for_fixed_channels():
    """Guard: the fast-path must not touch fixed channels (ATT/SMP/signaling),
    which have no LE CoC MTU/MPS semantics."""
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    # A first fragment on the ATT fixed channel with a huge declared length.
    pkt = _first_fragment_pkt(0x000C, 0x0004, declared_len=9999, payload=b"\x02\x00")
    await m.on_acl_data(pkt)            # must not raise / disconnect
    # ATT channel still present, nothing sent on signaling channel.
    assert 0x0004 in m._connections[0x000C]
    sig_ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_receive_uses_our_advertised_mps_not_negotiated_min():
    """BV-07 regression: the K-frame violation check must validate inbound
    frames against the MTU/MPS *we* advertised (our receive capacity), NOT the
    negotiated min(ours, peer). The peer may legally send frames up to OUR MPS
    even when its own MPS (which bounds what WE send) is smaller."""
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    delivered = {}
    m.listen_le_coc_channel(psm=0x0080, handler=lambda ch: delivered.update(channel=ch))
    # Peer (initiator) can only RECEIVE 64-byte frames (req.mps=64) and 120-byte
    # SDUs (req.mtu=120); we advertise 247/512. So peer may SEND us up to 247/512.
    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=120, mps=64, initial_credits=5,
    )
    pdu = encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x10, req.encode(),
    )
    await m._on_le_signaling(handle=0x000C, data=pdu)
    ch = delivered["channel"]
    # Negotiated (send-path) values are the min; receive limits are ours.
    assert ch._mps == 64 and ch._mtu == 120
    assert ch._rx_mps == 247 and ch._rx_mtu == 512

    got = []
    ch.set_events(SimpleChannelEvents(on_data=lambda d: got.append(d)))
    sig_ch.send.reset_mock()
    # A 100-byte SDU in a single frame: payload (2 + 100) = 102 > min-MPS 64 but
    # <= our advertised MPS 247, and SDU 100 <= our MTU 512. Must be accepted.
    await ch._on_pdu((100).to_bytes(2, "little") + b"v" * 100)
    assert got == [b"v" * 100]
    assert ch.cid in m._le_channels     # channel NOT torn down


@pytest.mark.asyncio
async def test_incoming_connect_enforces_required_security():
    """A listener registered with required_security refuses an incoming CoC
    connect whose link doesn't meet the level, then accepts after the stack
    reports the link secured (PTS L2CAP/LE/CFC/BV-11/13/15/25 security-responder).
    """
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    # Listener requiring ENCRYPTION (BTP L2CAPConnectionResponse.insufficient_encryption=4).
    m.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None, required_security=4)

    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=247, mps=247, initial_credits=5,
    )
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x10, req.encode())

    # 1) Unencrypted link → refused with 0x0008 (insufficient encryption), no channel.
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE
    assert payload.result == 0x0008
    assert m._le_channels == {}

    # 2) Stack reports the link encrypted → retry is now accepted.
    m.set_le_connection_security(0x000C, encrypted=True, authenticated=True, key_size=16)
    sig_ch.send.reset_mock()
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert payload.result == 0x0000
    assert len(m._le_channels) == 1


@pytest.mark.asyncio
async def test_disconnect_request_unknown_dcid_command_rejected(manager_with_open_channel):
    """BV-23: a DISCONNECTION_REQ naming an unrecognised (or fixed-channel) DCID
    must be answered with COMMAND_REJECT_RSP Reason=0x0002, not a Disconnection
    Response and not silence."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    # Unknown DCID 0x0077 (no such channel).
    req = DisconnectionRequest(dcid=0x0077, scid=ch._peer_cid)
    pdu = encode_le_signaling(LE_SIG_DISCONNECTION_REQUEST, 0x30, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_COMMAND_REJECT
    assert payload.reason == 0x0002
    # Real channel NOT torn down.
    assert ch.cid in m._le_channels


@pytest.mark.asyncio
async def test_disconnect_request_fixed_channel_dcid_command_rejected(manager_with_open_channel):
    """BV-23 step 3-4: a DISCONNECTION_REQ naming a fixed channel (e.g. the LE
    signaling CID 0x0005) is also rejected with Reason=0x0002."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    req = DisconnectionRequest(dcid=CID_LE_SIGNALING, scid=0x0040)
    pdu = encode_le_signaling(LE_SIG_DISCONNECTION_REQUEST, 0x31, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_COMMAND_REJECT
    assert payload.reason == 0x0002


@pytest.mark.asyncio
async def test_disconnect_request_valid_dcid_gets_response(manager_with_open_channel):
    """A DISCONNECTION_REQ for an established channel still gets a Disconnection
    Response and tears the channel down (no regression from the BV-23 gate)."""
    m, sig_ch, ch = manager_with_open_channel
    sig_ch.send.reset_mock()
    req = DisconnectionRequest(dcid=ch.cid, scid=ch._peer_cid)
    pdu = encode_le_signaling(LE_SIG_DISCONNECTION_REQUEST, 0x32, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_DISCONNECTION_RESPONSE
    assert ch.cid not in m._le_channels


@pytest.mark.asyncio
async def test_incoming_connect_duplicate_scid_refused():
    """BV-20: a second connect request reusing the Source CID of an established
    channel must be refused with Result=0x000A (Source CID already allocated),
    not accepted as a new channel."""
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    m.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None)

    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=247, mps=247, initial_credits=5,
    )
    pdu1 = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x10, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu1)
    assert len(m._le_channels) == 1          # first connect accepted

    # Second request, SAME source CID (new ident) → refused 0x000A, still 1 channel.
    sig_ch.send.reset_mock()
    pdu2 = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x11, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu2)
    sent = sig_ch.send.await_args.args[0]
    code, _, payload = decode_le_signaling(sent)
    assert code == LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE
    assert payload.result == 0x000A
    assert len(m._le_channels) == 1

    # A DIFFERENT source CID is still accepted (no false positive).
    sig_ch.send.reset_mock()
    req3 = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0061, mtu=247, mps=247, initial_credits=5,
    )
    pdu3 = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x12, req3.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu3)
    sent = sig_ch.send.await_args.args[0]
    _, _, payload = decode_le_signaling(sent)
    assert payload.result == 0x0000
    assert len(m._le_channels) == 2


@pytest.mark.asyncio
async def test_incoming_connect_no_required_security_accepts_unencrypted():
    """required_security=0 (success) accepts even on an unencrypted link — the
    default listener behaviour the non-security L2CAP cases rely on."""
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    m = L2CAPManager(hci=hci)
    await m.on_connection(handle=0x000C, link_type=LinkType.LE,
                          peer_address=None, role=None)
    sig_ch = m._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    m.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None)  # default: no requirement

    req = LECreditBasedConnectionRequest(
        le_psm=0x0080, scid=0x0060, mtu=247, mps=247, initial_credits=5,
    )
    pdu = encode_le_signaling(LE_SIG_LE_CREDIT_BASED_CONNECTION_REQUEST, 0x10, req.encode())
    await m._on_le_signaling(handle=0x000C, data=pdu)
    sent = sig_ch.send.await_args.args[0]
    _, _, payload = decode_le_signaling(sent)
    assert payload.result == 0x0000
    assert len(m._le_channels) == 1
