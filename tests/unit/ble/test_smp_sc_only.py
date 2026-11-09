"""Secure Connections Only mode enforcement (GAP/SEC/SEM/BV-28/29).

In SC-only mode the IUT rejects pairing with a peer that does not support
LE Secure Connections: a peripheral's Security Request without the SC bit
(either direction) and a legacy Pairing Request/Response exchange each get
SMP Pairing Failed "Authentication Requirements" (0x03) per Core Vol 3
Part H 2.3.4 / GAP 10.2.4 — the legacy pairing must NOT complete.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import (
    SMPCode, SMPManager, SMPPairingRequest, SMPSecurityRequest,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
PEER = BDAddress(b"\x01\x02\x03\x04\x05\x06")


def _sc_only_manager(mitm_required: bool = False) -> tuple[SMPManager, list[bytes]]:
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True,
                                       sc_only_mode=True,
                                       mitm_required=mitm_required),
    )
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    return mgr, sent


def _legacy_request() -> bytes:
    return SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01,  # bonding only — NO SC bit
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes()


@pytest.mark.asyncio
async def test_sc_only_rejects_legacy_security_request():
    """BV-29: a peripheral's Security Request without SC in SC-only mode gets
    Pairing Failed 0x03 (Authentication Requirements), never a Pairing Request."""
    mgr, sent = _sc_only_manager()
    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x01).to_bytes(),
                     connection_handle=HANDLE)

    assert sent and sent[0][0] == SMPCode.PAIRING_FAILED
    assert sent[0][1] == 0x03, "reason must be Authentication Requirements"
    assert all(p[0] != SMPCode.PAIRING_REQUEST for p in sent), \
        "no legacy Pairing Request may go out in SC-only mode"
    assert mgr.get_context(HANDLE) is None


@pytest.mark.asyncio
async def test_sc_only_rejects_legacy_pairing_request_as_responder():
    """Legacy Pairing Request (no SC bit) toward an SC-only responder gets
    Pairing Failed 0x03 instead of a Pairing Response."""
    mgr, sent = _sc_only_manager()
    await mgr.on_pdu(_legacy_request(), connection_handle=HANDLE)

    assert sent and sent[0][0] == SMPCode.PAIRING_FAILED
    assert sent[0][1] == 0x03
    assert all(p[0] != SMPCode.PAIRING_RESPONSE for p in sent)


@pytest.mark.asyncio
async def test_sc_only_rejects_legacy_pairing_response_as_initiator():
    """BV-28 (outgoing): our Pairing Request is answered without the SC bit —
    abort with Pairing Failed 0x03, never continue the legacy exchange."""
    from pybluehost.ble.smp import SMPPairingResponse
    mgr, sent = _sc_only_manager()
    await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST

    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01,  # NO SC bit
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)

    assert any(p[0] == SMPCode.PAIRING_FAILED and p[1] == 0x03 for p in sent)


@pytest.mark.asyncio
async def test_sc_only_accepts_sc_pairing():
    """SC pairing proceeds normally in SC-only mode (sanity)."""
    from pybluehost.ble.smp import SMPPairingRequest
    mgr, sent = _sc_only_manager()
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09,  # bonding + SC
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    assert sent and sent[0][0] == SMPCode.PAIRING_RESPONSE


@pytest.mark.asyncio
async def test_sc_only_initiator_request_does_not_force_mitm():
    """GAP/SEC/SEM/BV-41 + BV-43 are SC-only **mode 1 level 2** — UNAUTHENTICATED.

    GAP.TS Table 4.17/4.18 pair each level-3 case (BV-42/44, MITM) with a level-2
    twin (BV-41/43, no MITM). PTS's level-2 responder answers AuthReq 0x09 (no
    MITM), so a request carrying MITM splits the association models — we compute
    passkey display while PTS computes Just Works — and the LT disconnects right
    after the public key (on-air capture 2026-11-01: IUT `01 00 00 0d 10 07 07`
    vs PTS `02 04 00 09 10 00 00`). SC-only constrains the *SC bit*, not MITM.
    """
    mgr, sent = _sc_only_manager(mitm_required=False)
    await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][3] & 0x08, "SC bit set"
    assert not sent[0][3] & 0x04, "level 2 SC-only must NOT set MITM"


@pytest.mark.asyncio
async def test_sc_only_initiator_request_honours_config_mitm():
    """GAP/SEC/SEM/BV-42 + BV-44 (SC-only level 3) need authenticated pairing:
    the per-case pre-condition turns MITM on and the request must carry it."""
    mgr, sent = _sc_only_manager(mitm_required=True)
    await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][3] & 0x08, "SC bit set"
    assert sent[0][3] & 0x04, "level 3 requires MITM (from the config)"
