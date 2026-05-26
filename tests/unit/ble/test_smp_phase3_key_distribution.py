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


async def test_phase3_defers_peer_keys_until_encryption_change(tmp_path, monkeypatch):
    """Real controllers can deliver peer keys before local Encryption_Change."""
    monkeypatch.setattr(os, "urandom", lambda n: b"\xAB" * n)

    from pybluehost.ble._smp_state import register_transitions
    from pybluehost.ble.smp import (
        PairingRole,
        SMPEncryptionInformation,
        SMPIdentityAddressInformation,
        SMPIdentityInformation,
        SMPMasterIdentification,
        SMPPairingContext,
        SMPSigningInformation,
    )

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
    peer_addr = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    mgr.bind_channel(0x0040, send=send, peer_address=peer_addr)
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=peer_addr,
        role=PairingRole.RESPONDER,
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
    register_transitions(ctx)
    mgr._contexts[0x0040] = ctx
    ctx.state_machine._state = SMPState.RANDOM_EXCHANGE

    peer_ltk = b"\xDE" * 16
    peer_ediv = 0x9876
    peer_rand = b"\xEF" * 8
    await mgr.on_pdu(
        SMPEncryptionInformation(long_term_key=peer_ltk).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPMasterIdentification(ediv=peer_ediv, rand=peer_rand).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPIdentityInformation(irk=b"\xF0" * 16).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPIdentityAddressInformation(
            addr_type=0, bd_addr=bytes(peer_addr.address),
        ).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPSigningInformation(signature_key=b"\xCC" * 16).to_bytes(),
        connection_handle=0x0040,
    )

    assert ctx.state_machine.state == SMPState.RANDOM_EXCHANGE
    assert len(ctx.pending_phase3_pdus) == 5
    assert not ctx.pairing_complete.done()

    await ctx.state_machine.fire(SMPEvent.ENCRYPTION_CHANGE_SUCCESS)

    await asyncio.wait_for(ctx.pairing_complete, timeout=1.0)
    assert ctx.pending_phase3_pdus == []
    assert ctx.state_machine.state == SMPState.BONDED
    assert SMPCode.ENCRYPTION_INFORMATION in [pdu[0] for pdu in sent]

    bond = await storage.load_bond(peer_addr)
    assert bond is not None
    assert bond.ltk == b"\xAB" * 16
    assert bond.ediv == 0xABAB
    assert bond.rand == b"\xAB" * 8


async def test_sc_initiator_phase3_skips_ltk_distribution(tmp_path, monkeypatch):
    """In SC mode, Initiator does NOT send SMPEncryptionInformation/SMPMasterIdentification.
    Bond is persisted with sc=True and ltk=ctx.ltk_sc."""
    monkeypatch.setattr(os, "urandom", lambda n: b"\xAB" * n)

    from pybluehost.ble._smp_state import register_transitions
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        PairingRole,
        SMPIdentityAddressInformation,
        SMPIdentityInformation,
        SMPPairingContext,
        SMPSigningInformation,
    )

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    storage = JsonBondStorage(tmp_path / "bonds.json")
    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT,
        bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
        local_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"),
        bond_storage=storage,
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    # Build context in SC mode + force into STK_ENCRYPTING
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.local_io_caps = IOCapability.NO_INPUT_NO_OUTPUT
    ctx.bondable = True
    ctx.local_address = BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F")
    ctx.security_config = SecurityConfig(enable_secure_connections=True)
    ctx._bond_storage = storage
    # In SC, EncKey bit (0x01) is typically cleared at negotiation; mask=0x06 => IdKey + Sign
    ctx.local_init_key_dist = 0x06
    ctx.local_resp_key_dist = 0x06
    ctx.peer_init_key_dist = 0x06
    ctx.peer_resp_key_dist = 0x06
    # SC negotiated (both sides advertise SC bit 0x08):
    ctx.local_auth_req = 0x09
    ctx.peer_auth_req = 0x09
    ctx.ltk_sc = b"\xDE" * 16
    ctx.mac_key = b"\xCC" * 16
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)
    mgr._contexts[0x0040] = ctx
    ctx.state_machine._state = SMPState.STK_ENCRYPTING

    await ctx.state_machine.fire(SMPEvent.ENCRYPTION_CHANGE_SUCCESS)

    # Initiator should send IRK + IdentityAddress + CSRK — NOT EncryptionInformation/MasterIdentification
    sent_codes = [pdu[0] for pdu in sent]
    assert SMPCode.ENCRYPTION_INFORMATION not in sent_codes, "SC mode must NOT distribute LTK"
    assert SMPCode.MASTER_IDENTIFICATION not in sent_codes, "SC mode must NOT distribute EDIV/RAND"
    assert SMPCode.IDENTITY_INFORMATION in sent_codes
    assert SMPCode.IDENTITY_ADDRESS_INFORMATION in sent_codes
    assert SMPCode.SIGNING_INFORMATION in sent_codes
    sent.clear()

    # Receive peer's IRK + IdentityAddress + CSRK (no peer LTK in SC)
    peer_irk = b"\xF0" * 16
    peer_csrk = b"\xCD" * 16
    await mgr.on_pdu(
        SMPIdentityInformation(irk=peer_irk).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPIdentityAddressInformation(
            addr_type=0, bd_addr=bytes(BDAddress(b"\x01\x02\x03\x04\x05\x06").address)
        ).to_bytes(),
        connection_handle=0x0040,
    )
    await mgr.on_pdu(
        SMPSigningInformation(signature_key=peer_csrk).to_bytes(),
        connection_handle=0x0040,
    )

    await asyncio.wait_for(ctx.pairing_complete, timeout=1.0)

    bond = await storage.load_bond(BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    assert bond is not None
    assert bond.sc is True
    assert bond.authenticated is False
    assert bond.ltk == b"\xDE" * 16  # f5-derived LTK_sc
    assert bond.irk == peer_irk
    assert bond.csrk == peer_csrk
    assert ctx.state_machine.state == SMPState.BONDED
