"""Security Request answered by a Pairing Request means the bond is lost.

GAP/SEC/AUT/BV-22-C (Lost Bond - Responder role): the whole verdict is the
IUT reporting the lost bond when the central answers our Security Request
with a Pairing Request instead of encryption (MSC: Security Request ->
Pairing Request -> Bond Lost). A central that still holds the bond answers
the request by encrypting (Core Vol 3 Part H §3.6.1), so "pairing instead"
is the lost-bond signal — the same family as the Key-Missing (0x06) path.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import (
    BondInfo,
    InMemoryBondStorage,
    SMPManager,
    SMPPairingRequest,
)
from pybluehost.ble.security import SecurityConfig
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
PEER = BDAddress(b"\x01\x02\x03\x04\x05\x06")


async def _manager(*, bond: bool) -> tuple[SMPManager, list[bytes], list[tuple[int, BDAddress | None]]]:
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    storage = InMemoryBondStorage()
    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
        bond_storage=storage,
    )
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    lost: list[tuple[int, BDAddress | None]] = []
    mgr.on_bond_lost(lambda handle, peer: lost.append((handle, peer)))
    if bond:
        await storage.save_bond(BondInfo(peer_address=PEER, ltk=b"\xCC" * 16, sc=True))
    return mgr, sent, lost


async def _run_responder(mgr: SMPManager) -> None:
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x09,  # bonding + SC, no MITM
        max_key_size=16, init_key_dist=0x00, resp_key_dist=0x02,
    ).to_bytes(), connection_handle=HANDLE)


@pytest.mark.asyncio
async def test_pairing_request_after_security_request_reports_bond_lost():
    mgr, sent, lost = await _manager(bond=True)
    await mgr.request_security(HANDLE)

    await _run_responder(mgr)

    assert lost == [(HANDLE, PEER)]
    # The pairing itself must still proceed normally.
    assert sent and sent[-1][0] == 0x02


@pytest.mark.asyncio
async def test_pairing_request_without_outstanding_security_request_keeps_quiet():
    """Fresh responder pairings (SM/PER family) must never emit bond-lost."""
    mgr, sent, lost = await _manager(bond=True)

    await _run_responder(mgr)

    assert lost == []
    assert sent and sent[-1][0] == 0x02


@pytest.mark.asyncio
async def test_pairing_request_without_stored_bond_keeps_quiet():
    """SecReq without a bond (BV-13-style fresh pair) is a normal §3.6.1
    pairing response, not a lost bond."""
    mgr, sent, lost = await _manager(bond=False)
    await mgr.request_security(HANDLE)

    await _run_responder(mgr)

    assert lost == []
    assert sent and sent[-1][0] == 0x02


@pytest.mark.asyncio
async def test_security_request_mark_is_cleared_on_unbind():
    mgr, _sent, lost = await _manager(bond=True)
    await mgr.request_security(HANDLE)
    mgr.unbind_channel(HANDLE)
    # Rebind the same handle: the stale SecReq mark must be gone.
    async def send(data: bytes) -> None:
        pass
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)

    await _run_responder(mgr)

    assert lost == []


@pytest.mark.asyncio
async def test_pair_wait_skips_security_request_when_pairing_already_in_flight():
    """GAP/SEC/AUT/BV-22 step after Bond Lost: the LT is already pairing with
    us (its Pairing Request started the responder). A second Security Request
    now interrupts the peer's pairing — the LT answers Pairing Failed. When a
    live context exists, pair() must just wait for it."""
    mgr, sent, lost = await _manager(bond=True)
    await _run_responder(mgr)  # LT-initiated pairing now in flight
    ctx = mgr.get_context(HANDLE)
    ctx.pairing_complete.set_result(None)
    sent.clear()

    await mgr.request_security_and_wait(HANDLE)

    assert not [p for p in sent if p[0] == 0x0B], "no Security Request mid-pairing"
    assert lost == []
