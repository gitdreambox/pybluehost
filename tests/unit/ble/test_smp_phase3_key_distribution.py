"""Phase 3: key distribution + bond persistence."""
from __future__ import annotations

import asyncio
import os

import pytest

from pybluehost.ble.smp import (
    BondInfo,
    JsonBondStorage,
    SMPCode,
    SMPEvent,
    SMPManager,
    SMPState,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


async def test_phase3_initiator_sends_keys_then_collects_and_bonds(tmp_path, monkeypatch):
    """After encryption is on, Initiator distributes its keys, receives peer's keys,
    persists a BondInfo, resolves pairing_complete."""
    monkeypatch.setattr(os, "urandom", lambda n: b"\xAB" * n)

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT,
        bondable=True,
        local_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"),
        bond_storage=storage,
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    # Shortcut: build context in KEY_DISTRIBUTION state by going through Phase 1+2
    # then manually nudging the state for unit-test brevity.
    from pybluehost.ble.smp import SMPPairingContext, PairingRole
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.local_io_caps = IOCapability.NO_INPUT_NO_OUTPUT
    ctx.bondable = True
    ctx.local_address = BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F")
    ctx._bond_storage = storage
    ctx.local_init_key_dist = 0x07
    ctx.local_resp_key_dist = 0x07
    ctx.peer_init_key_dist = 0x07
    ctx.peer_resp_key_dist = 0x07
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    from pybluehost.ble._smp_state import register_transitions
    register_transitions(ctx)
    mgr._contexts[0x0040] = ctx

    # Force state machine to STK_ENCRYPTING (post-Phase 2 entry)
    ctx.state_machine._state = SMPState.STK_ENCRYPTING

    # Trigger Phase 3 entry
    await ctx.state_machine.fire(SMPEvent.ENCRYPTION_CHANGE_SUCCESS)
    # After firing, Initiator should have sent: EncryptionInfo + MasterIdent + IdentityInfo + IdentityAddr + SigningInfo
    sent_codes = [pdu[0] for pdu in sent]
    assert SMPCode.ENCRYPTION_INFORMATION in sent_codes
    assert SMPCode.MASTER_IDENTIFICATION in sent_codes
    assert SMPCode.IDENTITY_INFORMATION in sent_codes
    assert SMPCode.IDENTITY_ADDRESS_INFORMATION in sent_codes
    sent.clear()

    # Now feed peer's keys
    from pybluehost.ble.smp import (
        SMPEncryptionInformation, SMPIdentityAddressInformation,
        SMPIdentityInformation, SMPMasterIdentification,
        SMPSigningInformation,
    )
    peer_ltk = b"\xDE" * 16
    peer_ediv = 0x9876
    peer_rand = b"\xEF" * 8
    peer_irk = b"\xF0" * 16

    await mgr.on_pdu(SMPEncryptionInformation(long_term_key=peer_ltk).to_bytes(),
                     connection_handle=0x0040)
    await mgr.on_pdu(SMPMasterIdentification(ediv=peer_ediv, rand=peer_rand).to_bytes(),
                     connection_handle=0x0040)
    await mgr.on_pdu(SMPIdentityInformation(irk=peer_irk).to_bytes(),
                     connection_handle=0x0040)
    # Note: SMPIdentityAddressInformation uses addr_type and bd_addr (raw bytes)
    await mgr.on_pdu(SMPIdentityAddressInformation(
        addr_type=0, bd_addr=bytes(b"\x01\x02\x03\x04\x05\x06")
    ).to_bytes(), connection_handle=0x0040)

    # CSRK is part of peer_resp_key_dist (0x04 bit); mask=0x07 includes it
    # Note: SMPSigningInformation uses signature_key (not csrk)
    await mgr.on_pdu(SMPSigningInformation(signature_key=b"\xCC" * 16).to_bytes(),
                     connection_handle=0x0040)

    await asyncio.wait_for(ctx.pairing_complete, timeout=1.0)

    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert bond.ltk == peer_ltk
    assert bond.ediv == peer_ediv
    assert bond.rand == peer_rand
    assert bond.irk == peer_irk
    assert ctx.state_machine.state == SMPState.BONDED
