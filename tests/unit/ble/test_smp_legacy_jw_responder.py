"""Responder-side Phase 1: receive Pairing Request, reply with Pairing Response."""
from __future__ import annotations

from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingRequest,
    SMPState,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


async def test_responder_acks_pairing_request_with_pairing_response():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0040,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    # Use actual field names from pybluehost/ble/smp.py:
    # io_capability, oob_data_flag, auth_req, max_key_size, init_key_dist, resp_key_dist
    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x01,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=0x0040)

    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_RESPONSE
    rsp = decode_smp_pdu(sent[0])
    assert rsp.io_capability == IOCapability.NO_INPUT_NO_OUTPUT
    assert rsp.auth_req & 0x01

    ctx = mgr.get_context(0x0040)
    assert ctx is not None
    assert ctx.state_machine.state == SMPState.CONFIRMING
