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


async def test_responder_completes_phase2(monkeypatch):
    """Responder: after sending Pairing Response, receives Initiator Confirm,
    replies with its own Confirm. Then receives Initiator Random, replies with
    its own Random. State advances to RANDOM_EXCHANGE."""
    import os
    monkeypatch.setattr(os, "urandom", lambda n: b"\x33" * n)

    from pybluehost.ble.smp import (
        SMPCrypto, SMPPairingConfirm, SMPPairingRandom,
    )
    # Patch c1 so verification always passes
    monkeypatch.setattr(SMPCrypto, "c1", staticmethod(lambda *a, **kw: b"\x44" * 16))
    monkeypatch.setattr(SMPCrypto, "s1", staticmethod(lambda *a, **kw: b"\x77" * 16))

    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
                     local_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"))
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))

    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01, max_key_size=16,
        init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=0x0040)
    sent.clear()

    # Initiator sends its Confirm — Responder generates Srand + own Confirm + sends
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\x44" * 16).to_bytes(),
                     connection_handle=0x0040)
    assert sent[-1][0] == SMPCode.PAIRING_CONFIRM
    sent.clear()

    # Initiator sends Random → Responder verifies, sends own Random
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x55" * 16).to_bytes(),
                     connection_handle=0x0040)
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM

    ctx = mgr.get_context(0x0040)
    assert ctx.state_machine.state == SMPState.RANDOM_EXCHANGE
    assert ctx.stk == b"\x77" * 16
