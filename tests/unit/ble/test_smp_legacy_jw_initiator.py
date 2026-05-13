"""Initiator-side Phase 1: send Pairing Request, accept Pairing Response."""
from __future__ import annotations

from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPManager,
    SMPPairingResponse,
    SMPState,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


async def test_initiator_sends_pairing_request_on_start():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0040,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    await mgr.start_initiator(connection_handle=0x0040)

    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_REQUEST

    ctx = mgr.get_context(0x0040)
    assert ctx is not None
    assert ctx.role == PairingRole.INITIATOR
    assert ctx.state_machine.state == SMPState.FEATURE_EXCHANGE


async def test_initiator_advances_on_pairing_response():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True)
    mgr.bind_channel(
        connection_handle=0x0040,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )
    await mgr.start_initiator(connection_handle=0x0040)
    sent.clear()

    # Use actual field names from pybluehost/ble/smp.py:
    # io_capability, oob_data_flag, auth_req, max_key_size, init_key_dist, resp_key_dist
    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x01,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=0x0040)

    ctx = mgr.get_context(0x0040)
    # After receiving response, initiator computes confirm and sends it
    assert ctx.state_machine.state == SMPState.CONFIRMING
    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_CONFIRM
