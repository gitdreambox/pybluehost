"""Legacy OOB pairing (Sub-Plan 3c).

PTS SM/*/OOB: PTS provisions a 16-byte OOB TK via BTP GAP OOB_LEGACY_SET_DATA
(0x18), then pairs. The IUT must advertise oob_data_flag=1 in the feature
exchange and use the provisioned TK (shared OOB data) for the legacy c1/s1
confirm/random exchange — not the Just Works all-zero TK, and not passkey.
"""
from __future__ import annotations

import asyncio

from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPManager,
    SMPPairingResponse,
    SMPPairingRequest,
    SMPState,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

OOB_TK = bytes.fromhex("eb10407c6506a761abb1a90ba2d24bd4")


def _make_manager() -> tuple[SMPManager, list[bytes]]:
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )
    return mgr, sent


async def test_initiator_advertises_oob_flag_and_uses_oob_tk():
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    fut = await mgr.start_initiator(0x0800)
    # Pairing Request: code, io_cap, oob_data_flag, auth_req, ...
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][2] == 0x01, "oob_data_flag must be 1 when an OOB TK is provisioned"

    # Peer responds (legacy, no SC); the OOB branch must set ctx.tk = OOB_TK and
    # send a Pairing Confirm computed with the OOB TK.
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=1,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)

    ctx = mgr.get_context(0x0800)
    assert ctx is not None
    assert ctx.tk == OOB_TK, "legacy OOB must use the provisioned OOB TK, not 0"
    assert sent[-1][0] == SMPCode.PAIRING_CONFIRM, "initiator sends Confirm with OOB TK"
    fut.cancel()


async def test_responder_advertises_oob_flag_and_uses_oob_tk():
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=1,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)

    # Pairing Response: code, io_cap, oob_data_flag, ...
    assert sent[0][0] == SMPCode.PAIRING_RESPONSE
    assert sent[0][2] == 0x01, "responder must advertise oob_data_flag=1"
    ctx = mgr.get_context(0x0800)
    assert ctx is not None
    assert ctx.role == PairingRole.RESPONDER
    assert ctx.tk == OOB_TK


async def test_responder_mirrors_bonding_bit_from_peer_request():
    """SM/PER/OOB/BV-02: PTS sends auth_req=0x04 (MITM, NO bonding) with
    key_dist=0x0000. The responder must NOT force the bonding bit on — claiming
    bonding while distributing no keys makes PTS expect a bond that never forms
    across the test's re-pair rounds -> INDCSV. Mirror the peer's Bonding_Flags
    (gated on local bondable) exactly like the SC/MITM bits are mirrored."""
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=1,
        auth_req=0x04, max_key_size=16, init_key_dist=0x00, resp_key_dist=0x00,
    ).to_bytes(), connection_handle=0x0800)

    assert sent[0][0] == SMPCode.PAIRING_RESPONSE
    assert not (sent[0][3] & 0x01), \
        "responder must not force bonding when the peer requested none"
    assert sent[0][3] & 0x04, "responder must still mirror the peer's MITM bit"


async def test_no_oob_data_leaves_flag_clear_and_tk_zero():
    mgr, sent = _make_manager()
    # No set_oob_legacy_data call.

    fut = await mgr.start_initiator(0x0800)
    assert sent[0][2] == 0x00, "oob_data_flag must be 0 without a provisioned TK"

    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=0,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)
    ctx = mgr.get_context(0x0800)
    # Just Works path: TK stays all-zero.
    assert ctx.tk == b"\x00" * 16
    fut.cancel()


async def test_initiator_falls_back_to_passkey_when_peer_has_no_oob():
    """SM/CEN/OOB/BV-03: IUT has OOB data (flag=1) but the responder does NOT
    (flag=0, MITM=1). OOB requires BOTH sides — the IUT must fall back to the
    IO-capability model (passkey entry here), NOT use its OOB TK."""
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    fut = await mgr.start_initiator(0x0800)
    assert sent[0][2] == 0x01, "IUT still advertises that IT has OOB data"

    # Responder: KeyboardOnly, no OOB data (flag=0), MITM=1.
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.KEYBOARD_ONLY, oob_data_flag=0,
        auth_req=0x05, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)
    ctx = mgr.get_context(0x0800)
    assert ctx.tk != OOB_TK, \
        "peer has no OOB data -> must fall back to passkey, not use the OOB TK"
    fut.cancel()


async def test_initiator_falls_back_to_just_works_when_peer_has_no_oob():
    """SM/CEN/OOB/BV-09: IUT has OOB data (flag=1) but the responder does NOT
    (flag=0, MITM=0, NoInputNoOutput) -> Just Works with an all-zero TK."""
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    fut = await mgr.start_initiator(0x0800)
    assert sent[0][2] == 0x01

    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)
    ctx = mgr.get_context(0x0800)
    assert ctx.tk == b"\x00" * 16, \
        "peer has no OOB data + no MITM -> Just Works, not the OOB TK"
    fut.cancel()


async def test_responder_falls_back_when_peer_has_no_oob():
    """SM/PER/OOB/BV-04: IUT (responder) has OOB data but the initiator does NOT
    (flag=0, MITM=1) -> fall back to passkey, not the OOB TK."""
    mgr, sent = _make_manager()
    mgr.set_oob_legacy_data(OOB_TK)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x05, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)
    ctx = mgr.get_context(0x0800)
    assert ctx.tk != OOB_TK, \
        "initiator has no OOB data -> must fall back to passkey, not use the OOB TK"
