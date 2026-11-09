"""Responder Pairing Response MITM bit: mirror the peer, unless the case asks.

SM/PER/KDU/BV-08-C: PTS's Pairing Request carries bonding+SC with NO MITM
(Table 4.6 cases are unauthenticated); a global SM-profile ``gap_set_mitm_on``
forcing the response's MITM bit on made PTS select passkey entry while we
computed Just Works — the models split and pairing died. So MITM is enabled
PER CASE now (pybluehost_iut/sm.py): with the policy off the response mirrors
the request, and the one case that must answer MITM against the peer's 0
(SM/PER/PKE/BV-05, SM.TS Table 4.3 v6.1-or-earlier) turns the policy on.
The initiator's REQUEST keeps taking MITM from the same config.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import SMPManager, SMPPairingRequest
from pybluehost.ble.security import SecurityConfig
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
PEER = BDAddress(b"\x01\x02\x03\x04\x05\x06")


def _manager(cfg) -> tuple[SMPManager, list[bytes]]:
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True,
        security_config=cfg,
    )
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    return mgr, sent


@pytest.mark.asyncio
async def test_responder_mitm_mirrors_request_when_config_mitm_off():
    """SM/PER/KDU/BV-08 + SM/PER/PKE/BV-06: with MITM off (the SM profile now
    enables it per case instead of globally) the response mirrors the peer's
    request bit, so an unauthenticated request gets an unauthenticated answer."""
    cfg = SecurityConfig(enable_secure_connections=True, mitm_required=False)
    mgr, sent = _manager(cfg)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x09,  # bonding + SC, NO MITM
        max_key_size=16, init_key_dist=0x00, resp_key_dist=0x02,
    ).to_bytes(), connection_handle=HANDLE)

    resp = sent[0]
    assert resp[0] == 0x02  # Pairing Response
    assert not (resp[3] & 0x04), "response MITM must mirror the request (clear)"
    assert resp[3] & 0x08, "SC bit stays set"
    assert resp[3] & 0x01, "bonding bit mirrors the request"
    assert resp[6] == 0x02, "responder key distribution mirrors the request mask"


@pytest.mark.asyncio
async def test_responder_mitm_forced_when_config_mitm_on():
    """SM/PER/PKE/BV-05 is the v6.1-or-earlier variant in SM.TS Table 4.3: the
    LT requests NoInputNoOutput + bonding=00 + MITM=0 yet the IUT's response
    MUST set MITM=1 (pass verdict: "In Step 2b, the IUT sets the MITM flag as
    specified in Table 4.3"). That per-case requirement travels through the
    config — its BV-06 twin (v6.2+) runs with MITM off and mirrors instead."""
    cfg = SecurityConfig(enable_secure_connections=True, mitm_required=True)
    mgr, sent = _manager(cfg)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x08,  # SC, no bonding, NO MITM
        max_key_size=16, init_key_dist=0x00, resp_key_dist=0x00,
    ).to_bytes(), connection_handle=HANDLE)

    resp = sent[0]
    assert resp[0] == 0x02
    assert resp[3] & 0x04, "BV-05 requires MITM in the response"


@pytest.mark.asyncio
async def test_responder_mitm_set_when_peer_requests_it():
    cfg = SecurityConfig(enable_secure_connections=True, mitm_required=False)
    mgr, sent = _manager(cfg)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_ONLY, oob_data_flag=0,
        auth_req=0x0D,  # bonding + MITM + SC
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)

    resp = sent[0]
    assert resp[3] & 0x04, "response MITM must mirror the request (set)"
