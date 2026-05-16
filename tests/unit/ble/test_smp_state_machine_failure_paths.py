"""SMP state-machine failure-path coverage: TIMEOUT, DISCONNECTED, PAIRING_FAILED_RX."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.ble._smp_state import register_transitions
from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPEvent,
    SMPPairingContext,
    SMPPairingFailed,
    SMPState,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress


async def test_pairing_failed_rx_transitions_to_failed_state():
    """Inbound SMPPairingFailed PDU drives state machine to FAILED + rejects pairing future."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)

    # Push state into FEATURE_EXCHANGE by firing LOCAL_PAIR_REQUEST
    await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
    sent.clear()

    # Peer sends PAIRING_FAILED — should advance to FAILED, not echo back
    failed = SMPPairingFailed(reason=0x05)  # PAIRING_NOT_SUPPORTED
    await ctx.state_machine.fire(SMPEvent.PAIRING_FAILED_RX, pdu=failed)

    assert ctx.state_machine.state == SMPState.FAILED
    assert sent == [], "must not echo SMPPairingFailed back to peer on inbound failure"
    assert ctx.pairing_complete.done()
    with pytest.raises(RuntimeError):
        ctx.pairing_complete.result()


async def test_disconnected_event_drives_to_failed_state():
    """Firing DISCONNECTED on an active context drives state machine to FAILED."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.RESPONDER,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)

    # Push the responder into CONFIRMING by firing a synthetic Pairing Request.
    from pybluehost.ble.smp import SMPPairingRequest
    from pybluehost.core.types import IOCapability
    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x01,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await ctx.state_machine.fire(SMPEvent.PAIRING_REQ_RX, pdu=req)
    sent.clear()

    await ctx.state_machine.fire(SMPEvent.DISCONNECTED)

    assert ctx.state_machine.state == SMPState.FAILED
    assert sent == [], "must not send PDUs after disconnect"


async def test_timeout_drives_to_failed_state_and_sends_pairing_failed():
    """Firing TIMEOUT sends a PAIRING_FAILED PDU with reason=Unspecified and goes FAILED."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    ctx = SMPPairingContext.create(
        connection_handle=0x0040,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        role=PairingRole.INITIATOR,
        send=send,
    )
    ctx.pairing_complete = asyncio.get_running_loop().create_future()
    register_transitions(ctx)
    await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
    sent.clear()

    await ctx.state_machine.fire(SMPEvent.TIMEOUT)

    assert ctx.state_machine.state == SMPState.FAILED
    assert len(sent) == 1
    pdu = decode_smp_pdu(sent[0])
    assert isinstance(pdu, SMPPairingFailed)
    assert pdu.reason == 0x08  # Unspecified
    assert ctx.pairing_complete.done()
    with pytest.raises(RuntimeError):
        ctx.pairing_complete.result()
