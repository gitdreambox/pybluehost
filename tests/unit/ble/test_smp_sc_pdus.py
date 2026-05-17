"""SMP Secure Connections PDU encode/decode + enum extensions."""
from __future__ import annotations

from pybluehost.ble.smp import (
    SMPCode,
    SMPPairingDHKeyCheck,
    SMPPairingPublicKey,
    decode_smp_pdu,
)


def test_pairing_public_key_round_trip():
    pdu = SMPPairingPublicKey(
        public_key_x=bytes(range(32)),
        public_key_y=bytes(range(32, 64)),
    )
    raw = pdu.to_bytes()
    assert raw[0] == SMPCode.PAIRING_PUBLIC_KEY
    assert len(raw) == 1 + 64
    decoded = decode_smp_pdu(raw)
    assert isinstance(decoded, SMPPairingPublicKey)
    assert decoded.public_key_x == bytes(range(32))
    assert decoded.public_key_y == bytes(range(32, 64))


def test_pairing_dhkey_check_round_trip():
    pdu = SMPPairingDHKeyCheck(dhkey_check=bytes(range(16)))
    raw = pdu.to_bytes()
    assert raw[0] == SMPCode.PAIRING_DHKEY_CHECK
    assert len(raw) == 1 + 16
    decoded = decode_smp_pdu(raw)
    assert isinstance(decoded, SMPPairingDHKeyCheck)
    assert decoded.dhkey_check == bytes(range(16))


def test_state_enum_has_sc_states():
    from pybluehost.ble.smp import SMPState
    assert "PUBLIC_KEY_EXCHANGE" in {s.name for s in SMPState}
    assert "DHKEY_CHECK" in {s.name for s in SMPState}


def test_event_enum_has_sc_events():
    from pybluehost.ble.smp import SMPEvent
    assert "PAIRING_PUBLIC_KEY_RX" in {e.name for e in SMPEvent}
    assert "PAIRING_DHKEY_CHECK_RX" in {e.name for e in SMPEvent}


def test_context_has_sc_fields():
    from pybluehost.ble.smp import PairingRole, SMPPairingContext
    from pybluehost.core.address import BDAddress
    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
    )
    assert ctx.local_private_key == b""
    assert ctx.local_public_key == b""
    assert ctx.peer_public_key == b""
    assert ctx.dhkey == b""
    assert ctx.mac_key == b""
    assert ctx.ltk_sc == b""
    assert ctx.local_dhkey_check == b""
    assert ctx.peer_dhkey_check == b""
