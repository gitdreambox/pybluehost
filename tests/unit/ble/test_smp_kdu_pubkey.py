"""SC peer public-key validation (SM/*/KDU/BI-04).

PTS sends an invalid P-256 public key (off-curve, (0,0), y=0, bit-flipped, …).
The IUT must reject it with Pairing Failed "DHKey Check Failed" (0x0B) instead of
computing a DHKey from the bad point (which would either raise uncaught in the
PDU handler and hang, or — worse — complete the pairing).
"""
from __future__ import annotations

import pytest

from pybluehost.ble._smp_sc_crypto import generate_p256_keypair, peer_public_key_valid
from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingPublicKey,
    SMPPairingRequest,
    SMPPairingResponse,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
IUT_ADDR = BDAddress(b"\x11\x22\x33\x44\x55\x66")
PEER_ADDR = BDAddress(b"\x01\x02\x03\x04\x05\x06")

# (0, 0) is not on the P-256 curve.
INVALID_PUBKEY = b"\x00" * 64


def _make_manager():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_YES_NO,
        bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.set_local_address(IUT_ADDR)
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER_ADDR)
    return mgr, sent


def _sc_response() -> bytes:
    return SMPPairingResponse(
        io_capability=IOCapability.DISPLAY_YES_NO, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes()


def test_peer_public_key_valid_unit():
    _, valid_pub = generate_p256_keypair()
    assert peer_public_key_valid(valid_pub) is True
    assert peer_public_key_valid(INVALID_PUBKEY) is False, "(0,0) is off-curve"
    assert peer_public_key_valid(b"\x01" * 63) is False, "wrong length"
    # y = 0 with a valid-curve x is not a real point for P-256.
    assert peer_public_key_valid(valid_pub[:32] + b"\x00" * 32) is False


@pytest.mark.asyncio
async def test_initiator_rejects_invalid_peer_public_key():
    mgr, sent = _make_manager()
    fut = await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST

    await mgr.on_pdu(_sc_response(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_PUBLIC_KEY, "SC initiator sends its pubkey"

    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=b"\x00" * 32, public_key_y=b"\x00" * 32,
    ).to_bytes(), connection_handle=HANDLE)

    assert sent[-1][0] == SMPCode.PAIRING_FAILED
    assert sent[-1][1] == 0x0B, "reason must be DHKey Check Failed (0x0B)"
    with pytest.raises(RuntimeError):
        await fut


@pytest.mark.asyncio
async def test_initiator_accepts_valid_peer_public_key():
    mgr, sent = _make_manager()
    fut = await mgr.start_initiator(HANDLE)
    await mgr.on_pdu(_sc_response(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_PUBLIC_KEY

    _, valid_pub = generate_p256_keypair()
    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=valid_pub[:32], public_key_y=valid_pub[32:],
    ).to_bytes(), connection_handle=HANDLE)

    assert sent[-1][0] != SMPCode.PAIRING_FAILED, \
        "a valid peer pubkey must not be rejected"
    fut.cancel()


@pytest.mark.asyncio
async def test_responder_rejects_invalid_peer_public_key():
    mgr, sent = _make_manager()
    # Peer (initiator) opens with an SC Pairing Request.
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.DISPLAY_YES_NO, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_RESPONSE, "responder answers the request"

    # Initiator's (invalid) public key arrives -> validate + reject before we
    # send our own public key.
    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=b"\x00" * 32, public_key_y=b"\x00" * 32,
    ).to_bytes(), connection_handle=HANDLE)

    assert sent[-1][0] == SMPCode.PAIRING_FAILED
    assert sent[-1][1] == 0x0B
