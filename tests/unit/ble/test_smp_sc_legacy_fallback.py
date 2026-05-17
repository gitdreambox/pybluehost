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
