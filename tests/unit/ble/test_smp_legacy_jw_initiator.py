"""Initiator-side Phase 1: send Pairing Request, accept Pairing Response."""
from __future__ import annotations

from pybluehost.ble.smp import (
    PairingRole,
    SMPCode,
    SMPPairingContext,
    SMPPairingRequest,
    SMPManager,
    SMPPairingResponse,
    SMPState,
)
from pybluehost.ble._smp_state import _build_c1_params
from pybluehost.core.address import AddressType, BDAddress
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


async def test_initiator_completes_phase2_and_starts_encryption(monkeypatch):
    """Initiator: after sending Confirm, receives peer Confirm + Random, derives STK,
    issues HCI_LE_Start_Encryption."""
    import os
    monkeypatch.setattr(os, "urandom", lambda n: b"\x11" * n)

    from pybluehost.ble.smp import (
        SMPCrypto, SMPPairingConfirm, SMPPairingRandom,
    )

    # Bypass real c1: any peer_confirm we send should "verify"
    monkeypatch.setattr(SMPCrypto, "c1", staticmethod(lambda *a, **kw: b"\x44" * 16))
    monkeypatch.setattr(SMPCrypto, "s1", staticmethod(lambda *a, **kw: b"\x88" * 16))

    sent: list[bytes] = []
    enc_starts: list = []

    async def send(data: bytes) -> None:
        sent.append(data)

    class FakeHCI:
        async def send_command(self, cmd):
            from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
            assert isinstance(cmd, HCI_LE_Start_Encryption_Command)
            enc_starts.append(cmd)

    mgr = SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT, bondable=True,
        local_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"),
        hci=FakeHCI(),
    )
    mgr.bind_channel(0x0040, send=send, peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    await mgr.start_initiator(0x0040)
    sent.clear()

    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01, max_key_size=16,
        init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=0x0040)
    # State should be CONFIRMING, local Confirm sent
    assert sent[-1][0] == SMPCode.PAIRING_CONFIRM
    sent.clear()

    # Peer sends its Confirm (any 16 bytes — c1 is patched to always return 0x44...)
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\x44" * 16).to_bytes(),
                     connection_handle=0x0040)
    # Peer sends its Random
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x22" * 16).to_bytes(),
                     connection_handle=0x0040)

    # Initiator should have issued Start_Encryption with STK as LTK
    assert enc_starts, "no Start_Encryption command issued"
    assert enc_starts[0].long_term_key == b"\x88" * 16
    ctx = mgr.get_context(0x0040)
    assert ctx.state_machine.state == SMPState.STK_ENCRYPTING


def test_initiator_c1_params_use_hci_address_order_and_types():
    ctx = SMPPairingContext.create(
        connection_handle=0x0044,
        peer_address=BDAddress.from_string("D4:54:8B:BA:70:A1"),
        role=PairingRole.INITIATOR,
    )
    ctx.local_address = BDAddress.from_string(
        "6E:03:9A:3C:E2:96",
        type=AddressType.RANDOM,
    )
    ctx.saved_pairing_request = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x01,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    ).to_bytes()
    ctx.saved_pairing_response = SMPPairingResponse(
        io_capability=IOCapability.KEYBOARD_DISPLAY,
        oob_data_flag=0,
        auth_req=0x2D,
        max_key_size=16,
        init_key_dist=0x0F,
        resp_key_dist=0x0F,
    ).to_bytes()

    preq, pres, iat, rat, ia, ra = _build_c1_params(ctx)

    assert preq == bytes.fromhex("01030001100707")
    assert pres == bytes.fromhex("0204002d100f0f")
    assert iat == AddressType.RANDOM
    assert rat == AddressType.PUBLIC
    assert ia == bytes.fromhex("96e23c9a036e")
    assert ra == bytes.fromhex("a170ba8b54d4")
