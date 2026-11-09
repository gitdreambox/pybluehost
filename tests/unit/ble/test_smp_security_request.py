"""Central responds to a peripheral's Security Request by initiating pairing.

PTS GAP/SEC/AUT: PTS (peripheral, GATT client) reads a protected IUT
characteristic, gets Insufficient Authentication, then sends an SMP Security
Request expecting the IUT (central) to start pairing. Previously the Security
Request was dropped ("no context") and pairing never began.
"""
from __future__ import annotations

from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPManager,
    SMPSecurityRequest,
    SMPState,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


async def test_security_request_starts_initiator_pairing():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    # Peripheral asks us (central) to pair, requesting bonding+MITM+SC.
    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0800)

    # A Pairing Request went out and an initiator context now exists.
    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    ctx = mgr.get_context(0x0800)
    assert ctx is not None
    assert ctx.role == PairingRole.INITIATOR
    assert ctx.state_machine.state == SMPState.FEATURE_EXCHANGE


async def test_security_request_mitm_bit_propagates_to_pairing_request():
    """The peripheral's MITM request must be honoured, else the association
    degrades to Just Works (unauthenticated) and the protected characteristic
    that prompted the Security Request stays unreadable."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0800)

    auth_req = sent[0][3]  # Pairing Request: code, io_cap, oob, auth_req
    assert auth_req & 0x04, "MITM bit not set despite peer requesting it"
    assert auth_req & 0x01, "bonding bit should be set (bondable=True)"


async def test_security_request_without_mitm_leaves_mitm_clear():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    # mitm_required is False by default; a Security Request without the MITM
    # bit must not force it on.
    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x01).to_bytes(), connection_handle=0x0800)

    auth_req = sent[0][3]
    assert not (auth_req & 0x04), "MITM must not be set when the peer did not ask"


async def test_security_request_sc_only_overrides_config_mitm():
    """SM/CEN/PIS/BV-03: the SM profile turns MITM on globally (gap_set_mitm_on),
    but a Security Request asking SC-only (0x08, no MITM) must yield Just Works.
    Forcing config MITM would make the peer choose passkey entry while we compute
    JW → association-model mismatch → PTS times out waiting for a passkey."""
    from pybluehost.ble.security import SecurityConfig

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    cfg = SecurityConfig(enable_secure_connections=True, mitm_required=True)
    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True, security_config=cfg)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    # Peripheral asks for SC-only encryption, no MITM.
    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x08).to_bytes(), connection_handle=0x0800)

    auth_req = sent[0][3]  # Pairing Request: code, io_cap, oob, auth_req
    assert not (auth_req & 0x04), "MITM must mirror the Security Request (clear), not config"
    assert auth_req & 0x08, "SC bit should be set (enable_secure_connections)"
    assert auth_req & 0x01, "bonding bit should be set (bondable=True)"


async def test_security_request_on_unbound_handle_does_not_raise():
    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    # No bind_channel: nothing to send on; must be swallowed, not raised.
    await mgr.on_pdu(SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0999)
    assert mgr.get_context(0x0999) is None


async def test_request_security_and_wait_sends_security_request_then_resolves():
    """Peripheral path used by stack.pair when the link role is peripheral: a
    Security Request goes out, and the call resolves once the central's Pairing
    Request spawns a responder context whose pairing then completes."""
    import asyncio

    from pybluehost.ble.smp import SMPPairingRequest

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    wait_task = asyncio.ensure_future(
        mgr.request_security_and_wait(0x0800, auth_req=0x0D, timeout=5.0))
    # Let the Security Request go out and the wait loop start polling.
    await asyncio.sleep(0.05)
    assert sent and sent[0][0] == SMPCode.SECURITY_REQUEST
    assert sent[0][1] == 0x0D

    # Central answers with a Pairing Request -> responder context is created.
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=0x0800)
    await asyncio.sleep(0.05)
    ctx = mgr.get_context(0x0800)
    assert ctx is not None
    # Complete the pairing; the waiter must return.
    ctx.pairing_complete.set_result(None)
    await asyncio.wait_for(wait_task, timeout=1.0)


async def test_request_security_and_wait_times_out_without_central():
    import asyncio

    import pytest

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )
    with pytest.raises(RuntimeError):
        await mgr.request_security_and_wait(0x0800, auth_req=0x0D, timeout=0.1)


async def test_security_request_after_bonding_restarts_pairing():
    """PTS GAP/SEC/AUT/BV-13: after a Just Works pairing completes, the peer
    sends a Security Request asking for a *higher* level (MITM). The PDU must
    still be handled — with a live BONDED context it used to fall through to
    "Unhandled SMP opcode 0x0B" and PTS gave up with Pairing Failed."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )
    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x05).to_bytes(), connection_handle=0x0800,
    )
    ctx = mgr.get_context(0x0800)
    assert ctx is not None
    # Simulate the Just Works pairing having finished.
    ctx.state_machine._state = SMPState.BONDED   # simulate a finished pairing
    sent.clear()

    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0800,
    )

    # A fresh Pairing Request carrying the newly requested MITM bit.
    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][3] & 0x04      # MITM bit from auth_req 0x0D


async def test_security_request_while_pairing_in_progress_is_ignored():
    """Mid-pairing the PDU must NOT restart anything (the context is live)."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0800,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )
    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x05).to_bytes(), connection_handle=0x0800,
    )
    sent.clear()   # ctx is now in FEATURE_EXCHANGE (pairing underway)

    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0800,
    )

    assert sent == []


class _OneBondStorage:
    def __init__(self, bond):
        self._bond = bond

    async def load_bond(self, address):
        return self._bond


async def test_security_request_met_by_existing_bond_does_not_repair():
    """GAP/BROB/BCST/BV-03, GAP/BOND/BON/BV-04: on a bonded reconnect the
    peer's Security Request asks for the link to be *encrypted* with the
    distributed LTK, not re-paired. Pairing anyway left PTS silent — it is not
    prepared to pair again — and the case died on our 30 s timeout. The on-air
    trace is a lone Pairing Request with no response.

    The request is a demand for an encrypted link, so the IUT must go on to
    start the LL encryption procedure (GAP/SEC/AUT/BV-13 step 2)."""
    from pybluehost.ble.smp import BondInfo

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    bond = BondInfo(peer_address=peer, address_type=0, ltk=b"\xCC" * 16, sc=True)
    sent: list[bytes] = []
    resumed: list[tuple[int, object, int]] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    async def resume(handle: int, resumed_bond: object, auth_req: int) -> None:
        resumed.append((handle, resumed_bond, auth_req))

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT,
                     bondable=True, bond_storage=_OneBondStorage(bond))
    mgr.set_peer_address_provider(lambda h: peer)
    mgr.set_bond_resume_handler(resume)
    mgr.bind_channel(connection_handle=0x0800, send=send, peer_address=peer)

    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x09).to_bytes(), connection_handle=0x0800,
    )

    assert sent == [], (
        "a bonding+SC bond already covers auth_req 0x09; encrypt, don't re-pair"
    )
    assert resumed == [(0x0800, bond, 0x09)], (
        "covering bond: encryption must actually start, not just skip pairing"
    )


async def test_security_request_met_by_bond_without_resume_handler_is_harmless():
    """Stack wires the resume handler, but SMP must not require one."""
    from pybluehost.ble.smp import BondInfo

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    bond = BondInfo(peer_address=peer, address_type=0, ltk=b"\xCC" * 16, sc=True)
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT,
                     bondable=True, bond_storage=_OneBondStorage(bond))
    mgr.set_peer_address_provider(lambda h: peer)
    mgr.bind_channel(connection_handle=0x0800, send=send, peer_address=peer)

    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x09).to_bytes(), connection_handle=0x0800,
    )

    assert sent == []


async def test_security_request_above_the_bond_still_pairs():
    """The mirror case (GAP/SEC/AUT/BV-13): a Just Works bond cannot satisfy a
    MITM request, so a fresh authenticated pairing must still start."""
    from pybluehost.ble.smp import BondInfo

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    bond = BondInfo(peer_address=peer, address_type=0, ltk=b"\xCC" * 16,
                    sc=False, authenticated=False)
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.DISPLAY_ONLY,
                     bondable=True, bond_storage=_OneBondStorage(bond))
    mgr.set_peer_address_provider(lambda h: peer)
    mgr.bind_channel(connection_handle=0x0800, send=send, peer_address=peer)

    await mgr.on_pdu(
        SMPSecurityRequest(auth_req=0x0D).to_bytes(), connection_handle=0x0800,
    )

    assert sent and sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][3] & 0x04      # MITM bit from auth_req 0x0D
