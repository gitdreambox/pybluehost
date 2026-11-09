"""Peer-initiated Pairing Failed notification (SM/*/KDU/BI-02/03).

When the Lower Tester aborts a pairing by sending a Pairing Failed PDU, the IUT
must report it to the Upper Tester. A responder has no pair() waiter, so the SMP
manager surfaces it via on_pairing_failed -> BTP GAP PAIRING_FAILED.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import SMPCode, SMPManager, SMPPairingFailed, SMPPairingRequest
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
IUT_ADDR = BDAddress(b"\x11\x22\x33\x44\x55\x66")
PEER_ADDR = BDAddress(b"\x01\x02\x03\x04\x05\x06")


def _make_manager():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.set_local_address(IUT_ADDR)
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER_ADDR)
    return mgr, sent


@pytest.mark.asyncio
async def test_peer_pairing_failed_notifies_listener_with_reason():
    mgr, sent = _make_manager()
    events: list[tuple[int, object, int]] = []
    mgr.on_pairing_failed(lambda h, peer, reason: events.append((h, peer, reason)))

    # Peer (initiator) opens pairing -> responder context created.
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=0,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_RESPONSE

    # Peer aborts with Pairing Failed (Key Rejected 0x0F).
    await mgr.on_pdu(SMPPairingFailed(reason=0x0F).to_bytes(), connection_handle=HANDLE)

    assert events == [(HANDLE, PEER_ADDR, 0x0F)], \
        "listener must fire with the handle, peer address, and the peer's reason"
    # We must NOT echo a Pairing Failed back to the peer.
    assert all(b[0] != SMPCode.PAIRING_FAILED for b in sent)


@pytest.mark.asyncio
async def test_peer_pairing_failed_without_listener_does_not_raise():
    mgr, sent = _make_manager()
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=0,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    # No listener registered — must still transition to FAILED cleanly.
    await mgr.on_pdu(SMPPairingFailed(reason=0x05).to_bytes(), connection_handle=HANDLE)
    ctx = mgr.get_context(HANDLE)
    assert ctx is None or ctx.pairing_complete is None or ctx.pairing_complete.done()
