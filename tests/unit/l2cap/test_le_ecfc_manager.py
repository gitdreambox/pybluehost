"""L2CAPManager ECFC (Enhanced Credit-Based) — 0x17/0x18 multi-channel flows."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.errors import LECoCConnectError
from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    ECFCConnectionRequest,
    ECFCConnectionResponse,
    LE_SIG_ECFC_CONNECTION_REQUEST,
    LE_SIG_ECFC_CONNECTION_RESPONSE,
    LE_SIG_ECFC_RECONFIGURE_REQUEST,
    decode_le_signaling,
    encode_le_signaling,
)
from pybluehost.l2cap.manager import L2CAPManager


@pytest.fixture
async def m():
    hci = MagicMock(); hci.send_acl_data = AsyncMock()
    mgr = L2CAPManager(hci=hci)
    await mgr.on_connection(handle=0x000C, link_type=LinkType.LE,
                            peer_address=None, role=None)
    sig_ch = mgr._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()
    return mgr, sig_ch


def _ecfc_req(psm=0x0080, scids=(0x0060, 0x0061), mtu=247, mps=247, credits=5):
    return ECFCConnectionRequest(le_psm=psm, mtu=mtu, mps=mps,
                                 initial_credits=credits, scids=scids)


# ---- responder (0x17 in → 0x18 out) ----------------------------------------


@pytest.mark.asyncio
async def test_incoming_ecfc_request_accepts_all_channels(m):
    """PTS connects N ECFC channels: one 0x17 with N SCIDs → one 0x18 with N
    DCIDs + N channels created + listener invoked N times (PTS L2CAP/ECFC/*)."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10, _ecfc_req().encode(),
    ))

    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_ECFC_CONNECTION_REQUEST + 1  # 0x18 response code
    assert ident == 0x10
    assert isinstance(payload, ECFCConnectionResponse)
    assert payload.result == 0x0000
    assert len(payload.dcids) == 2
    # Two channels created, one per requested SCID.
    assert len(seen) == 2
    assert len(mgr._le_channels) == 2
    # Each channel's peer CID matches the corresponding requested SCID, in order.
    assert [ch._peer_cid for ch in seen] == list(_ecfc_req().scids)


@pytest.mark.asyncio
async def test_incoming_ecfc_request_enforces_required_security(m):
    """L2CAP/ECFC/BV-11/13/15: an ECFC request on a PSM that requires
    authentication must be refused with result 0x0005 and NO channels created
    (the ECFC twin of the legacy-CFC security-responder path)."""
    mgr, sig_ch = m
    # BTP L2CAPConnectionResponse.insufficient_authentication = 1.
    mgr.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None,
                              required_security=1)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10, _ecfc_req().encode(),
    ))

    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_ECFC_CONNECTION_REQUEST + 1  # 0x18
    assert payload.result == 0x0005  # insufficient authentication
    assert payload.dcids == ()
    assert len(mgr._le_channels) == 0


@pytest.mark.asyncio
async def test_ecfc_refusal_pads_zero_dcids_matching_scid_count(m):
    """A refused ECFC response still carries one DCID slot per requested SCID,
    zero-filled — zephyr's l2cap_ecred_conn_rsp does exactly this ("set dcid to
    zeros here, in case of all connections refused error") and PTS's parser
    expects the slots to be present. Omitting them makes PTS wait forever
    (L2CAP/ECFC/BV-11/13/15)."""
    mgr, sig_ch = m
    mgr.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None,
                              required_security=1)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10, _ecfc_req().encode(),
    ))

    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_ECFC_CONNECTION_REQUEST + 1  # 0x18
    assert payload.result == 0x0005
    # One zero DCID slot per requested SCID (the fixture requests two) — assert
    # on the raw bytes because the decoder drops refusal padding by design.
    assert len(sent) == 4 + 8 + 2 * 2
    assert sent[4 + 8:] == b"\x00\x00\x00\x00"
    assert len(mgr._le_channels) == 0


@pytest.mark.asyncio
async def test_ecfc_refusal_with_single_scid_pads_one_dcid(m):
    """Same rule with a single requested channel: 0x18 body is 10 bytes
    (MTU+MPS+Credits+Result+one zero DCID)."""
    mgr, sig_ch = m
    mgr.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None,
                              required_security=1)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x11, _ecfc_req(scids=(0x0060,)).encode(),
    ))

    raw = sig_ch.send.await_args.args[0]
    assert len(raw) == 14  # 4 header + 8 fields + one zero DCID
    code, ident, payload = decode_le_signaling(raw)
    assert payload.result == 0x0005
    assert raw[-2:] == b"\x00\x00"


@pytest.mark.asyncio
async def test_incoming_ecfc_request_unknown_psm_refuses_all(m):
    mgr, sig_ch = m
    mgr.listen_le_coc_channel(psm=0x0080, handler=lambda ch: None)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x11,
        _ecfc_req(psm=0x00FF).encode(),
    ))

    sent = sig_ch.send.await_args.args[0]
    _, _, payload = decode_le_signaling(sent)
    assert isinstance(payload, ECFCConnectionResponse)
    assert payload.result == 0x0002          # PSM not supported
    assert payload.dcids == ()
    assert mgr._le_channels == {}


@pytest.mark.asyncio
async def test_incoming_ecfc_request_enforces_listener_security(m):
    """required_security=4 (encryption): unencrypted link → 0x18 refused with
    0x0008; after set_le_connection_security, retry accepts (PTS ECFC
    security-responder cases BV-24/25/31/32)."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append, required_security=4)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x12, _ecfc_req().encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert payload.result == 0x0008
    assert seen == []

    mgr.set_le_connection_security(0x000C, encrypted=True,
                                   authenticated=True, key_size=16)
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x13, _ecfc_req().encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert payload.result == 0x0000
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_recycled_handle_starts_unencrypted(m):
    """Security state must not survive a disconnect: controllers recycle
    connection handles, and PTS L2CAP/LE/CFC/BV-25 (and ECFC/BV-32) pair on one
    connection, drop it, reconnect on the *same* handle, and request the CoC
    channel before encryption is re-established. A stale "encrypted" entry made
    the encryption-required listener accept that request, so the case ended
    INDCSV instead of observing the 0x0008 refusal it asserts."""
    mgr, _ = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append, required_security=4)

    # Connection 1: paired and encrypted.
    mgr.set_le_connection_security(0x000C, encrypted=True,
                                   authenticated=True, key_size=16)
    await mgr.on_disconnection(0x000C, reason=0x13)

    # Connection 2, same handle, encryption not yet re-established.
    await mgr.on_connection(handle=0x000C, link_type=LinkType.LE,
                            peer_address=None, role=None)
    sig_ch = mgr._connections[0x000C][CID_LE_SIGNALING]
    sig_ch.send = AsyncMock()

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x14, _ecfc_req().encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert payload.result == 0x0008
    assert seen == []


# ---- initiator (multi-channel outgoing) ------------------------------------


@pytest.mark.asyncio
async def test_connect_le_coc_channels_sends_ecfc_and_builds_all(m):
    mgr, sig_ch = m
    task = asyncio.create_task(mgr.connect_le_coc_channels(
        handle=0x000C, psm=0x0080, mtu=512, mps=247,
        initial_credits=10, num=3, timeout=2.0,
    ))
    await asyncio.sleep(0); await asyncio.sleep(0)

    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == LE_SIG_ECFC_CONNECTION_REQUEST
    assert isinstance(payload, ECFCConnectionRequest)
    assert payload.le_psm == 0x0080
    assert len(payload.scids) == 3

    resp = ECFCConnectionResponse(
        mtu=247, mps=247, initial_credits=5, result=0x0000,
        dcids=(0x0050, 0x0051, 0x0052),
    )
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_RESPONSE, ident, resp.encode(),
    ))
    chans = await task
    assert len(chans) == 3
    assert [c._peer_cid for c in chans] == [0x0050, 0x0051, 0x0052]
    assert len(mgr._le_channels) == 3


@pytest.mark.asyncio
async def test_connect_le_coc_channels_refused_raises_typed_error(m):
    mgr, _ = m
    task = asyncio.create_task(mgr.connect_le_coc_channels(
        handle=0x000C, psm=0x0080, num=2, timeout=2.0,
    ))
    await asyncio.sleep(0); await asyncio.sleep(0)
    # feed refusal
    resp = ECFCConnectionResponse(
        mtu=0, mps=0, initial_credits=0, result=0x0004, dcids=(),
    )
    ident = 1
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_RESPONSE, ident, resp.encode(),
    ))
    with pytest.raises(LECoCConnectError) as ei:
        await task
    assert ei.value.result == 0x0004
    assert mgr._le_channels == {}


# ---- reconfigure responder (0x19 in → 0x1A out) ------------------------------
#
# Result-code matrix confirmed against PTS L2CAP/ECFC/BI-03..07 + BV-23/25
# (bluez issue #1865). MTU baseline = negotiated channel MTU (`_mtu`); MPS
# baseline = advertised receive MPS (`_reconfig_base_mps` = 247, immutable).


async def _ecfc_channels(mgr, sig_ch, scids, mtu=264, mps=100):
    """Accept an incoming ECFC request and return the created channels."""
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append)
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10,
        ECFCConnectionRequest(le_psm=0x0080, mtu=mtu, mps=mps,
                              initial_credits=5, scids=scids).encode(),
    ))
    return seen


async def _reconfig(mgr, sig_ch, ident, mtu, mps, dcids):
    from pybluehost.l2cap.le_signaling import (
        ECFCReconfigureRequest, LE_SIG_ECFC_RECONFIGURE_REQUEST,
    )
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_RECONFIGURE_REQUEST, ident,
        ECFCReconfigureRequest(mtu=mtu, mps=mps, dcids=dcids).encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    return payload.result


@pytest.mark.asyncio
async def test_reconfigure_mtu_reduction_refused_0x0001(m):
    """BI-03: reducing the negotiated MTU is refused 0x0001 (any channel count)."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=65, mps=64)
    dcid = chans[0]._local_cid
    # negotiated MTU = min(512, 65) = 65; reconfigure to 64 -> MTU reduction.
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=64, mps=64, dcids=(dcid,)) == 0x0001


@pytest.mark.asyncio
async def test_reconfigure_mps_multi_channel_refused_0x0002(m):
    """BI-04: reducing MPS across >1 channel (MTU unchanged) is refused 0x0002."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060, 0x0061), mtu=264, mps=100)
    dcids = tuple(c._local_cid for c in chans)
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=264, mps=99, dcids=dcids) == 0x0002


@pytest.mark.asyncio
async def test_reconfigure_invalid_cid_refused_0x0003(m):
    """BI-05: an unknown Destination CID is refused 0x0003."""
    mgr, sig_ch = m
    await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=264, mps=100)
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=64, mps=64, dcids=(0x0055,)) == 0x0003


@pytest.mark.asyncio
async def test_reconfigure_mps_below_minimum_refused_0x0004(m):
    """BI-06: a reconfigure whose MPS is below the supported minimum (MPSMIN,
    the spec's 64-octet floor) is refused 0x0004 ("other unacceptable
    parameters"). Note this is *not* about increases — those are legal."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=264, mps=100)
    dcid = chans[0]._local_cid
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=264, mps=32, dcids=(dcid,)) == 0x0004


@pytest.mark.asyncio
async def test_reconfigure_mtu_increase_accepted_0x0000(m):
    """BV-23 (Renegotiate MTU — Responder): the Lower Tester asks to *grow* the
    MTU from 64 to 65 and the IUT must accept. Growing is the entire point of
    the MTU renegotiation cases — refusing increases made us answer 0x0004 and
    PTS dropped the ACL immediately after."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=64, mps=64)
    dcid = chans[0]._local_cid
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=65, mps=64, dcids=(dcid,)) == 0x0000
    assert chans[0]._mtu == 65
    assert chans[0]._rx_mtu == 512  # our receive limits are untouched by 0x19


@pytest.mark.asyncio
async def test_reconfigure_baseline_not_lowered_by_prior_success(m):
    """BI-07: after a successful single-channel MPS reduction mutates ``_rx_mps``,
    a later multi-channel reduction above that enforced value is STILL judged a
    reduction (0x0002), because the baseline is the immutable advertised MPS."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060, 0x0061, 0x0062), mtu=84, mps=74)
    dcids = tuple(c._local_cid for c in chans)
    # First: valid single-channel MPS reduction -> 0x0000, mutates _mps to 68.
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=84, mps=68, dcids=dcids[:1]) == 0x0000
    assert chans[0]._mps == 68
    assert chans[0]._rx_mps == 247  # advertised receive MPS untouched
    # Second: mps=71 (> enforced 68) across 2 channels must still be a *reduction*
    # relative to the advertised 247 -> 0x0002, not an increase (0x0004).
    assert await _reconfig(mgr, sig_ch, 0x03, mtu=84, mps=71, dcids=dcids[:2]) == 0x0002


@pytest.mark.asyncio
async def test_reconfigure_valid_single_channel_mps_reduction_0x0000(m):
    """BV-23/25: a single-channel MPS reduction (MTU unchanged) succeeds 0x0000."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=264, mps=100)
    dcid = chans[0]._local_cid
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=264, mps=80, dcids=(dcid,)) == 0x0000
    assert chans[0]._mps == 80


# ---- initiator reconfigure (0x19 out → 0x1A in) ------------------------------


@pytest.mark.asyncio
async def test_reconfigure_initiator_sends_and_applies_success(m):
    """L2CAP/ECFC/BV-22 (Renegotiate MTU — Initiator): sends 0x19 carrying the
    peer's DCIDs and the new MTU; on 0x1A result 0x0000 the negotiated MTU of
    the listed channels is updated."""
    from pybluehost.l2cap.le_signaling import (
        ECFCReconfigureResponse, LE_SIG_ECFC_RECONFIGURE_RESPONSE,
        LE_SIG_ECFC_RECONFIGURE_REQUEST as _REQ,
    )
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=264, mps=100)

    task = asyncio.ensure_future(
        mgr.reconfigure_le_coc_channels(0x000C, mtu=200, channels=chans))
    await asyncio.sleep(0.02)
    sent = sig_ch.send.await_args.args[0]
    code, ident, payload = decode_le_signaling(sent)
    assert code == _REQ
    assert payload.mtu == 200
    assert payload.dcids == tuple(c._peer_cid for c in chans), \
        "reconfigure lists the DESTINATION CIDs (the peer's CIDs)"

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_RECONFIGURE_RESPONSE, ident,
        ECFCReconfigureResponse(result=0x0000).encode(),
    ))
    await asyncio.wait_for(task, timeout=1.0)
    assert chans[0]._mtu == 200


@pytest.mark.asyncio
async def test_reconfigure_initiator_refusal_raises(m):
    from pybluehost.l2cap.le_signaling import (
        ECFCReconfigureResponse, LE_SIG_ECFC_RECONFIGURE_RESPONSE,
        LE_SIG_ECFC_RECONFIGURE_REQUEST as _REQ,
    )
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=264, mps=100)

    task = asyncio.ensure_future(
        mgr.reconfigure_le_coc_channels(0x000C, mtu=200, channels=chans))
    await asyncio.sleep(0.02)
    _, ident, _ = decode_le_signaling(sig_ch.send.await_args.args[0])
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_RECONFIGURE_RESPONSE, ident,
        ECFCReconfigureResponse(result=0x0001).encode(),
    ))
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_incoming_ecfc_request_with_mtu_below_64_is_refused(m):
    """L2CAP/ECFC/BV-26-C: the request asks for MTU < 64, which is outside the
    LE_MTU range of 64..65535 (§4.22). The IUT must answer 0x18 with
    result 0x000C (All connections refused - invalid parameters)."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x20,
        _ecfc_req(mtu=32, scids=(0x0060,)).encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert isinstance(payload, ECFCConnectionResponse)
    assert payload.result == 0x000C
    assert seen == []
    assert mgr._le_channels == {}


@pytest.mark.asyncio
async def test_incoming_ecfc_request_reusing_an_allocated_scid_is_refused(m):
    """L2CAP/ECFC/BV-20-C: the Lower Tester re-requests a channel using a Source
    CID we already own, alongside a fresh one. §4.25 calls result 0x000A "**Some**
    connections refused" — the duplicate keeps a zero DCID slot while the fresh
    channel is still established with a real DCID. Answering all-refused made PTS
    drop the ACL right after our response, and accepting the duplicate was worse
    still."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0080, handler=seen.append)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x21,
        _ecfc_req(scids=(0x0060,)).encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert payload.result == 0x0000
    assert len(seen) == 1

    sig_ch.send.reset_mock()
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x22,
        _ecfc_req(scids=(0x0060, 0x0061)).encode(),
    ))
    # Assert on the raw bytes: the decoder drops DCID slots for a non-zero
    # result by design, but PTS reads them.
    raw = sig_ch.send.await_args.args[0]
    assert len(raw) == 16  # 4 header + MTU/MPS/Credits/Result + two DCID slots
    assert int.from_bytes(raw[10:12], "little") == 0x000A
    assert int.from_bytes(raw[12:14], "little") == 0, "duplicate SCID slot must be zero"
    assert int.from_bytes(raw[14:16], "little") != 0, "the fresh SCID is still accepted"
    assert len(seen) == 2, "the non-duplicate channel is established"


@pytest.mark.asyncio
async def test_incoming_ecfc_request_during_our_own_request_is_a_collision(m):
    """L2CAP/TIM/BV-03-C: a request arriving while ours is outstanding collided
    with it. Table 4.17's "Some connections refused - insufficient resources
    available" (0x0004) is the answer — accepting it would break the test's
    whole point (the Lower Tester watches for the refusal, then waits out our
    back-off and accepts the retry)."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0027, handler=seen.append)
    mgr._outgoing_ecfc.add(0x000C)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x30,
        _ecfc_req(psm=0x0027, scids=(0x0060,)).encode(),
    ))
    _, _, payload = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert payload.result == 0x0004
    assert seen == []
    assert mgr._le_channels == {}


@pytest.mark.asyncio
async def test_connect_eatt_channels_retries_after_a_collision(m, monkeypatch):
    """An EATT connect refused with 0x0004 is a collision: back off, then send a
    fresh request (new identifier) — the retry is what TIM/BV-03-C grades."""
    from pybluehost.l2cap.constants import PSM_EATT
    from pybluehost.l2cap.le_signaling import (
        ECFCConnectionResponse,
        LE_SIG_ECFC_CONNECTION_REQUEST as REQ,
        LE_SIG_ECFC_CONNECTION_RESPONSE as RSP,
    )

    mgr, sig_ch = m
    monkeypatch.setattr(mgr, "_collision_backoff", lambda handle: 0.0)

    task = asyncio.ensure_future(mgr.connect_eatt_channels(0x000C, num=1))
    await asyncio.sleep(0.02)

    _, ident1, req1 = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert req1.le_psm == PSM_EATT
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        RSP, ident1,
        ECFCConnectionResponse(mtu=0, mps=0, initial_credits=0,
                               result=0x0004, dcids=(0,)).encode(),
    ))

    await asyncio.sleep(0.05)
    _, ident2, _ = decode_le_signaling(sig_ch.send.await_args.args[0])
    assert ident2 != ident1, "the retry must not reuse the identifier"
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        RSP, ident2,
        ECFCConnectionResponse(mtu=512, mps=247, initial_credits=5,
                               result=0x0000, dcids=(0x00A0,)).encode(),
    ))

    channels = await asyncio.wait_for(task, timeout=1.0)
    assert len(channels) == 1
    assert mgr._outgoing_ecfc == set(), "the in-flight marker must be cleared"


@pytest.mark.asyncio
async def test_incoming_ecfc_channels_carry_the_request_psm(m):
    """BTP DISCONNECT_EATT_CHANS picks EATT bearers out by channel.psm — an
    inbound ECFC channel must record the PSM it was created for."""
    mgr, sig_ch = m
    seen = []
    mgr.listen_le_coc_channel(psm=0x0027, handler=seen.append)

    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_REQUEST, 0x10, _ecfc_req(psm=0x0027).encode(),
    ))

    assert len(seen) == 2
    assert [ch.psm for ch in seen] == [0x0027, 0x0027]


@pytest.mark.asyncio
async def test_outbound_ecfc_channels_carry_the_psm(m):
    """Outbound ECFC channels must record the PSM they were opened on."""
    mgr, sig_ch = m
    task = asyncio.create_task(mgr.connect_le_coc_channels(
        handle=0x000C, psm=0x0027, mtu=512, mps=247,
        initial_credits=10, num=2, timeout=2.0,
    ))
    await asyncio.sleep(0); await asyncio.sleep(0)

    sent = sig_ch.send.await_args.args[0]
    _, ident, _ = decode_le_signaling(sent)
    resp = ECFCConnectionResponse(
        mtu=247, mps=247, initial_credits=5, result=0x0000,
        dcids=(0x0050, 0x0051),
    )
    await mgr._on_le_signaling(handle=0x000C, data=encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_RESPONSE, ident, resp.encode(),
    ))
    chans = await task
    assert [ch.psm for ch in chans] == [0x0027, 0x0027]


def test_le_coc_channel_psm_defaults_to_none():
    """LECoCChannel.psm defaults to None when not supplied."""
    from pybluehost.l2cap.ble import LECoCChannel
    ch = LECoCChannel(connection_handle=0x40, local_cid=0x41, peer_cid=0x42, hci=object())
    assert ch.psm is None


@pytest.mark.asyncio
async def test_reconfigure_accept_grows_send_limits_not_receive_limits(m):
    """BV-23 (Renegotiate MTU — Responder) full shape: Core §4.26 — the 0x19's
    MTU/MPS are the REQUESTER's new receive limits, so accepting them raises
    what WE may send (``_mtu``/``_mps``). The old code applied them to
    ``_rx_mtu``/``_rx_mps`` instead: auto-pts (told the new sizes via the 0x84
    event, which reads ``_mtu``/``_mps`` for the peer-facing values) kept
    sending 64-byte SDUs and the case's step 5 never saw the new sizes."""
    mgr, sig_ch = m
    chans = await _ecfc_channels(mgr, sig_ch, (0x0060,), mtu=64, mps=64)
    dcid = chans[0]._local_cid
    # Channel came up as mtu=min(512, 64)=64 / mps=min(247, 64)=64, advertised
    # receive limits 512/247.
    assert chans[0]._mtu == 64 and chans[0]._mps == 64
    assert await _reconfig(mgr, sig_ch, 0x02, mtu=256, mps=100, dcids=(dcid,)) == 0x0000
    # Send limits grew; receive limits untouched.
    assert chans[0]._mtu == 256
    assert chans[0]._mps == 100
    assert chans[0]._rx_mtu == 512
    assert chans[0]._rx_mps == 247
    # The refusal baselines are untouched by the accept (BI-07 discipline).
    assert chans[0]._reconfig_base_mps == 247
