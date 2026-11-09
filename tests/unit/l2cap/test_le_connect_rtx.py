"""Outgoing LE CoC connect response handling (Core Vol 3 Part A §5.2).

A signaling response must carry the request's identifier, and identifiers
identify ONE transaction — so the request is sent exactly ONCE and never
replayed on-air (an identifier replay is the L2CAP.TS BI-29 Fail condition;
the Lower Tester aborts the link after the first repeats). When nothing
valid answers inside the RTX window the transaction is abandoned and
surfaced as a refusal (``LECoCConnectError.RESULT_NO_RESPONSE``), like the
zephyr reference ``l2cap_rtx_timeout``.

The BI-29 round shape this must survive: the Lower Tester answers each round
with a SUCCESS response carrying identifier 0 (or a stale non-zero id) and a
fresh DCID — hardware: TX 0x14 id=2 → RX 0x15 id=3 result=0 → RX id=0
result=0 … No matching response ever comes; the IUT must ignore those,
abandon the round, and never reuse the identifier.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.core.errors import LECoCConnectError
from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_LE_SIGNALING
from pybluehost.l2cap.le_signaling import (
    ECFCConnectionResponse,
    LECreditBasedConnectionResponse,
    LE_SIG_ECFC_CONNECTION_RESPONSE,
    LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE,
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


@pytest.fixture
async def rtx(m, monkeypatch):
    mgr, sig_ch = m
    monkeypatch.setattr(L2CAPManager, "LE_CONNECT_RTX_INTERVAL", 0.02)
    return mgr, sig_ch


def _legacy_rsp(ident, result=0x0000, dcid=0x0060):
    return encode_le_signaling(
        LE_SIG_LE_CREDIT_BASED_CONNECTION_RESPONSE, ident,
        LECreditBasedConnectionResponse(
            dcid=dcid, mtu=512, mps=247, initial_credits=5, result=result,
        ).encode(),
    )


def _ecfc_rsp(ident, result=0x0000, dcids=(0x0060,)):
    return encode_le_signaling(
        LE_SIG_ECFC_CONNECTION_RESPONSE, ident,
        ECFCConnectionResponse(
            mtu=512, mps=247, initial_credits=5, result=result, dcids=dcids,
        ).encode(),
    )


@pytest.mark.asyncio
async def test_connect_request_is_sent_once_never_replayed(m):
    """The identifier identifies one transaction: after a wrong-id SUCCESS and
    silence, the same PDU must NOT be replayed on-air (the BI-29 Lower Tester
    treats the replay as its Fail condition and drops the link)."""
    mgr, sig_ch = m
    task = asyncio.ensure_future(mgr.connect_le_coc_channel(
        handle=0x000C, psm=0x0080, mtu=512, mps=247))
    await asyncio.sleep(0.05)
    _, ident1, _ = decode_le_signaling(sig_ch.send.await_args.args[0])

    # Wrong-identifier SUCCESS — ignored, and NO retransmission follows.
    await mgr._on_le_signaling(handle=0x000C, data=_legacy_rsp(ident1 + 1))
    await asyncio.sleep(0.08)   # several RTX windows' worth of silence
    assert sig_ch.send.await_count == 1, \
        "request was replayed on-air — identifier reuse"
    assert not task.done(), "silence alone must not fabricate an outcome"
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, LECoCConnectError):
        pass


@pytest.mark.asyncio
async def test_rtx_expiry_abandons_the_transaction_as_refusal(rtx):
    """No valid response within the window → the transaction is abandoned as
    LECoCConnectError(RESULT_NO_RESPONSE) — a refusal the BTP layer reports
    gracefully — and the pending future is cleaned up. A late response after
    abandonment resolves nothing."""
    mgr, sig_ch = rtx
    with pytest.raises(LECoCConnectError) as excinfo:
        await mgr.connect_le_coc_channel(
            handle=0x000C, psm=0x0080, mtu=512, mps=247)
    assert excinfo.value.result == LECoCConnectError.RESULT_NO_RESPONSE
    assert mgr._pending_le_connect == {}
    # Late response after abandonment: no crash, nothing to resolve.
    await mgr._on_le_signaling(handle=0x000C, data=_legacy_rsp(1))


@pytest.mark.asyncio
async def test_ecfc_matching_response_completes_the_connect(m):
    mgr, sig_ch = m
    task = asyncio.ensure_future(mgr.connect_le_coc_channels(
        0x000C, 0x0080, mtu=512, mps=247, num=1))
    await asyncio.sleep(0.05)
    _, ident1, _ = decode_le_signaling(sig_ch.send.await_args.args[0])
    # A wrong-id SUCCESS first (ignored), then the matching response.
    await mgr._on_le_signaling(handle=0x000C, data=_ecfc_rsp(ident1 + 2))
    await mgr._on_le_signaling(handle=0x000C, data=_ecfc_rsp(ident1))
    chans = await asyncio.wait_for(task, timeout=1.0)
    assert [c._peer_cid for c in chans] == [0x0060]
    assert mgr._pending_le_connect == {}


# ---- Invalid-ID refusal resolution (L2CAP.TS 4.4.1.7 / BI-29) ---------------
#
# When the Lower Tester DOES terminate a round with a refusal, that refusal
# may carry a non-matching identifier (round 1 hardware: saved-id refusal
# result=0x0004 after an id=0 SUCCESS). With a single outstanding request per
# link a non-zero-result response can only be OUR transaction's refusal —
# resolve it. A result=0 response with a wrong id stays ignored: treating a
# wrong-id SUCCESS as ours would fabricate a connection, exactly the behavior
# BI-29 fails the IUT for.


@pytest.mark.asyncio
async def test_mismatched_id_refusal_resolves_the_pending_connect(m):
    mgr, sig_ch = m
    task = asyncio.ensure_future(mgr.connect_le_coc_channel(
        handle=0x000C, psm=0x0080, mtu=512, mps=247))
    await asyncio.sleep(0.05)
    _, ident1, _ = decode_le_signaling(sig_ch.send.await_args.args[0])

    # id=0, non-zero result — the LT's round-refusal (observed: result=0x0004).
    await mgr._on_le_signaling(handle=0x000C, data=_legacy_rsp(0, result=0x0004))

    with pytest.raises(LECoCConnectError) as excinfo:
        await asyncio.wait_for(task, timeout=1.0)
    assert excinfo.value.result == 0x0004
    assert mgr._pending_le_connect == {}


@pytest.mark.asyncio
async def test_ecfc_mismatched_id_refusal_resolves_the_pending_connect(m):
    mgr, sig_ch = m
    task = asyncio.ensure_future(mgr.connect_le_coc_channels(
        0x000C, 0x0080, mtu=512, mps=247, num=1))
    await asyncio.sleep(0.05)
    _, ident1, _ = decode_le_signaling(sig_ch.send.await_args.args[0])

    # Stale non-zero id, non-zero result — same lenient path for 0x18.
    await mgr._on_le_signaling(handle=0x000C,
                               data=_ecfc_rsp(ident1 + 5, result=0x0005))

    with pytest.raises(LECoCConnectError) as excinfo:
        await asyncio.wait_for(task, timeout=1.0)
    assert excinfo.value.result == 0x0005


@pytest.mark.asyncio
async def test_mismatched_id_success_response_is_still_ignored(m):
    """A result=0 response with a wrong identifier must NOT complete the
    connect (that would fabricate a connection the LT never granted) — the
    round ends as a refusal by abandonment instead."""
    mgr, sig_ch = m
    task = asyncio.ensure_future(mgr.connect_le_coc_channel(
        handle=0x000C, psm=0x0080, mtu=512, mps=247))
    await asyncio.sleep(0.05)
    _, ident1, _ = decode_le_signaling(sig_ch.send.await_args.args[0])

    # Successful response with id=0 — ignored (BI-29 step 3 / step 6 stimulus).
    await mgr._on_le_signaling(handle=0x000C, data=_legacy_rsp(0))
    await asyncio.sleep(0.05)
    assert not task.done(), "wrong-id SUCCESS must not complete the connect"

    # The matching refusal still resolves immediately when it DOES come.
    await mgr._on_le_signaling(handle=0x000C,
                               data=_legacy_rsp(ident1, result=0x0004))
    with pytest.raises(LECoCConnectError) as excinfo:
        await asyncio.wait_for(task, timeout=1.0)
    assert excinfo.value.result == 0x0004


def test_default_rtx_interval_is_one_second():
    """Core Vol 3 Part A §6.2 allows RTX in 1..60 s; 1 s (the minimum) keeps
    BI-29's 253-round loop — each abandoned at ~1 s — inside its 360 s
    TSPX_time_guard (253 × ~1.15 s ≈ 291 s; at 2 s it is ~557 s and overruns)."""
    assert L2CAPManager.LE_CONNECT_RTX_INTERVAL == 1.0
