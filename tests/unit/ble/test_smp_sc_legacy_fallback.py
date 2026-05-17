"""SC vs Legacy mode selection: config-off ignores peer's SC offer."""
from __future__ import annotations

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingRequest,
    SMPPairingResponse,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


async def test_initiator_sets_sc_bit_when_enabled():
    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)

    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    req = decode_smp_pdu(sent[0])
    assert req.auth_req & 0x08, "SC bit (0x08) should be set when enable_secure_connections=True"


async def test_initiator_clears_sc_bit_when_disabled():
    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=False),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)

    req = decode_smp_pdu(sent[0])
    assert not (req.auth_req & 0x08), "SC bit must NOT be set when enable_secure_connections=False"


async def test_responder_clears_sc_bit_when_disabled_even_if_peer_offers():
    """Peer advertises SC; we don't have it enabled → respond without SC bit, fall back to Legacy."""
    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=False),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    # Peer's request advertises SC (auth_req=0x09 = Bonding | SC)
    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x09,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=0x0040)

    assert sent[0][0] == SMPCode.PAIRING_RESPONSE
    rsp = decode_smp_pdu(sent[0])
    assert not (rsp.auth_req & 0x08), "Responder must clear SC bit when config-off, even if peer offered SC"


async def test_sc_initiator_sends_public_key_after_pairing_request():
    """Initiator with SC config-on: after Pairing Response with SC bit, Initiator sends Pairing_Public_Key."""
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        SMPCode, SMPManager, SMPPairingResponse, SMPState,
    )
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability

    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)
    sent.clear()

    # Peer responds with SC bit
    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09,  # Bonding | SC
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=0x0040)

    # SC initiator must send a Pairing_Public_Key (not a Confirm)
    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_PUBLIC_KEY
    ctx = mgr.get_context(0x0040)
    assert ctx.state_machine.state == SMPState.PUBLIC_KEY_EXCHANGE
    assert ctx.local_private_key  # keypair generated
    assert ctx.local_public_key
    assert len(ctx.local_public_key) == 64


async def test_sc_initiator_handles_peer_public_key():
    """Initiator receives peer's Public Key -> computes DHKey, awaits peer Confirm."""
    from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        SMPCode, SMPManager, SMPPairingPublicKey, SMPPairingResponse, SMPState,
    )
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability

    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)
    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=0x0040)
    sent.clear()

    # Peer sends its public key
    _, peer_pub = generate_p256_keypair()
    pk_pdu = SMPPairingPublicKey(public_key_x=peer_pub[:32], public_key_y=peer_pub[32:])
    await mgr.on_pdu(pk_pdu.to_bytes(), connection_handle=0x0040)

    ctx = mgr.get_context(0x0040)
    assert ctx.peer_public_key == peer_pub
    assert ctx.dhkey  # computed
    assert len(ctx.dhkey) == 32
    # Initiator does NOT send Confirm in SC Just Works -- it waits for peer's Confirm
    assert sent == [], f"Initiator must not send a Confirm in SC mode; got {sent}"
    assert ctx.state_machine.state == SMPState.PUBLIC_KEY_EXCHANGE


async def test_sc_responder_handles_initiator_public_key():
    """Responder receives Initiator's Public Key -> sends own Public Key + Cb (f4-derived Confirm)."""
    from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        SMPCode, SMPManager, SMPPairingPublicKey, SMPPairingRequest, SMPState,
    )
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability

    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
        local_address=BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A"),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    # Initiator's Pairing Request with SC bit
    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=0x0040)
    # Responder has sent Pairing Response; clear for next assertion
    sent.clear()

    # Initiator sends Public Key
    _, peer_pub = generate_p256_keypair()
    pk_pdu = SMPPairingPublicKey(public_key_x=peer_pub[:32], public_key_y=peer_pub[32:])
    await mgr.on_pdu(pk_pdu.to_bytes(), connection_handle=0x0040)

    # Responder should send own Public Key + Confirm
    assert len(sent) == 2
    assert sent[0][0] == SMPCode.PAIRING_PUBLIC_KEY
    assert sent[1][0] == SMPCode.PAIRING_CONFIRM
    ctx = mgr.get_context(0x0040)
    assert ctx.peer_public_key == peer_pub
    assert ctx.dhkey
    assert ctx.local_random  # Nb generated
    assert ctx.local_confirm  # Cb computed
    # Responder advances to CONFIRMING (waiting for Initiator's Random/Na)
    assert ctx.state_machine.state == SMPState.CONFIRMING


async def test_sc_initiator_completes_phase2_with_f5_ltk(monkeypatch):
    """Initiator: peer Confirm + peer Random → f4 verify pass → f5 derive (MacKey, LTK_sc)."""
    import os
    monkeypatch.setattr(os, "urandom", lambda n: b"\xAA" * n)
    from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        SMPCode, SMPCrypto, SMPManager, SMPPairingConfirm,
        SMPPairingPublicKey, SMPPairingRandom, SMPPairingResponse, SMPState,
    )
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability

    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
        local_address=BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A"),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)
    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=0x0040)
    _, peer_pub = generate_p256_keypair()
    await mgr.on_pdu(
        SMPPairingPublicKey(public_key_x=peer_pub[:32], public_key_y=peer_pub[32:]).to_bytes(),
        connection_handle=0x0040,
    )
    sent.clear()

    # Patch f4 so peer-Confirm verification passes deterministically
    monkeypatch.setattr(SMPCrypto, "f4", staticmethod(lambda *a, **kw: b"\x44" * 16))
    # Patch f5 to return a deterministic (MacKey, LTK) tuple
    monkeypatch.setattr(SMPCrypto, "f5", staticmethod(lambda *a, **kw: (b"\x11" * 16, b"\x22" * 16)))

    # Peer sends its Confirm
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\x44" * 16).to_bytes(),
                     connection_handle=0x0040)
    # Initiator now sends Na
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM
    sent.clear()

    # Peer sends its Random (Nb)
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x55" * 16).to_bytes(),
                     connection_handle=0x0040)

    ctx = mgr.get_context(0x0040)
    assert ctx.state_machine.state == SMPState.RANDOM_EXCHANGE
    assert ctx.mac_key == b"\x11" * 16
    assert ctx.ltk_sc == b"\x22" * 16


async def test_sc_responder_completes_phase2_with_f5_ltk(monkeypatch):
    """Responder: receives Initiator's Random Na, sends own Nb, derives f5 (MacKey, LTK)."""
    import os
    monkeypatch.setattr(os, "urandom", lambda n: b"\xBB" * n)
    from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import (
        SMPCode, SMPCrypto, SMPManager, SMPPairingPublicKey, SMPPairingRandom,
        SMPPairingRequest, SMPState,
    )
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability

    sent: list[bytes] = []
    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
        local_address=BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A"),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x09, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=0x0040)
    _, peer_pub = generate_p256_keypair()
    monkeypatch.setattr(SMPCrypto, "f4", staticmethod(lambda *a, **kw: b"\x44" * 16))
    monkeypatch.setattr(SMPCrypto, "f5", staticmethod(lambda *a, **kw: (b"\x33" * 16, b"\x77" * 16)))
    await mgr.on_pdu(
        SMPPairingPublicKey(public_key_x=peer_pub[:32], public_key_y=peer_pub[32:]).to_bytes(),
        connection_handle=0x0040,
    )
    sent.clear()

    # Initiator sends Na
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x66" * 16).to_bytes(),
                     connection_handle=0x0040)
    # Responder sends own Nb
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM
    ctx = mgr.get_context(0x0040)
    assert ctx.state_machine.state == SMPState.RANDOM_EXCHANGE
    assert ctx.mac_key == b"\x33" * 16
    assert ctx.ltk_sc == b"\x77" * 16
