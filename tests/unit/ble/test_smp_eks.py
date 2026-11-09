"""Encryption Key Size negotiation check (Core Vol 3 Part H §2.3.4).

PTS SM/*/EKS/BI: the Lower Tester offers Max_Encryption_Key_Size one below the
minimum and expects the IUT to abort with Pairing Failed "Encryption Key Size"
(0x06) instead of continuing the pairing. The negotiated size is
min(local_max, peer_max); the spec floor is 7 octets.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingResponse,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
IUT_ADDR = BDAddress(b"\x11\x22\x33\x44\x55\x66")
PEER_ADDR = BDAddress(b"\x01\x02\x03\x04\x05\x06")


def _make_manager():
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_ONLY,
        bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.set_local_address(IUT_ADDR)
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER_ADDR)
    return mgr, sent


def _response(max_key_size: int) -> bytes:
    return SMPPairingResponse(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x09, max_key_size=max_key_size,
        init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes()


@pytest.mark.asyncio
async def test_initiator_rejects_undersized_peer_max_key_size():
    """Peer offers max_key_size=6 (< 7): IUT must send Pairing Failed 0x06 and
    abort rather than continue to phase 2."""
    mgr, sent = _make_manager()
    fut = await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST

    await mgr.on_pdu(_response(max_key_size=6), connection_handle=HANDLE)

    assert sent[-1][0] == SMPCode.PAIRING_FAILED, \
        "undersized negotiated key must abort with Pairing Failed"
    assert sent[-1][1] == 0x06, "reason must be Encryption Key Size (0x06)"
    with pytest.raises(RuntimeError):
        await fut


@pytest.mark.asyncio
async def test_initiator_accepts_full_peer_max_key_size():
    """Peer offers max_key_size=16: no rejection — pairing proceeds (SC public
    key is sent, not a Pairing Failed)."""
    mgr, sent = _make_manager()
    fut = await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST

    await mgr.on_pdu(_response(max_key_size=16), connection_handle=HANDLE)

    assert sent[-1][0] != SMPCode.PAIRING_FAILED
    assert sent[-1][0] == SMPCode.PAIRING_PUBLIC_KEY
    fut.cancel()


@pytest.mark.asyncio
async def test_responder_rejects_undersized_peer_max_key_size():
    """Responder direction (SM/PER/EKS/BI-02-C): the IUT as responder must also
    reject a peer Pairing Request that caps the key below the floor."""
    from pybluehost.ble.smp import SMPPairingRequest

    mgr, sent = _make_manager()
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x09, max_key_size=5,
        init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)

    assert sent[-1][0] == SMPCode.PAIRING_FAILED
    assert sent[-1][1] == 0x06


@pytest.mark.asyncio
async def test_stk_reduced_to_negotiated_key_size(monkeypatch):
    """SM/PER/EKS/BV-02-C: with a negotiated key size of 7 (peer offers 7, we
    offer 16), the derived STK must have its (16-7) most significant octets
    zeroed — Core Vol 3 Part H §2.3.4 — before it is used for the pairing-time
    encryption. Replying with the full 128-bit STK makes the LL MIC fail and
    the link drops."""
    import os

    from pybluehost.ble.smp import (
        SMPCrypto, SMPPairingConfirm, SMPPairingRandom, SMPPairingRequest,
        SMPState,
    )

    monkeypatch.setattr(SMPCrypto, "c1", staticmethod(lambda *a, **kw: b"\x44" * 16))
    monkeypatch.setattr(
        SMPCrypto, "s1",
        staticmethod(lambda *a, **kw: bytes(range(16))),  # 00 01 02 ... 0f
    )

    mgr, sent = _make_manager()
    # Legacy (no SC bit), NoInputNoOutput -> Just Works, key size 7.
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01, max_key_size=7,
        init_key_dist=0x01, resp_key_dist=0x01,
    ).to_bytes(), connection_handle=HANDLE)
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\x44" * 16).to_bytes(),
                     connection_handle=HANDLE)
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x55" * 16).to_bytes(),
                     connection_handle=HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert ctx.state_machine.state == SMPState.RANDOM_EXCHANGE
    assert ctx.stk == bytes(range(7)) + b"\x00" * 9, \
        "STK must keep only the 7 least significant octets (§2.3.4)"


@pytest.mark.asyncio
async def test_sc_ltk_reduced_to_negotiated_key_size(monkeypatch):
    """GATT/SR/GAR/BI-05 preamble: PTS pairs with SC *and* max_key_size=7. The
    SC public-key/DHKey-check flow completes, but PTS encrypts with a key
    reduced to the negotiated size — if our ltk_sc stays the full 128-bit f5
    output the LL MIC fails and the link drops (0x3D). The f5 LTK must honour
    the negotiated key size as well (no-op when the peer offers 16)."""
    from pybluehost.ble import _smp_state
    from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
    from pybluehost.ble.smp import (
        SMPPairingConfirm, SMPPairingPublicKey, SMPPairingRandom,
    )

    monkeypatch.setattr(
        _smp_state, "_sc_f5",
        staticmethod(lambda *a, **kw: (b"\x11" * 16, bytes(range(16)))),
    )
    monkeypatch.setattr(
        _smp_state, "_sc_f4", staticmethod(lambda *a, **kw: b"\xAA" * 16))
    monkeypatch.setattr(
        _smp_state, "_sc_f6", staticmethod(lambda *a, **kw: b"\x22" * 16))

    mgr, sent = _make_manager()
    fut = await mgr.start_initiator(HANDLE)
    # SC JW: peer responds with SC, no MITM, and max_key_size=7.
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.DISPLAY_ONLY, oob_data_flag=0,
        auth_req=0x09, max_key_size=7,
        init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    _, peer_pub = generate_p256_keypair()
    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=peer_pub[:32], public_key_y=peer_pub[32:],
    ).to_bytes(), connection_handle=HANDLE)
    # Responder's Cb (monkeypatched f4 verifies), then its Rb -> we derive f5.
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\xAA" * 16).to_bytes(),
                     connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x55" * 16).to_bytes(),
                     connection_handle=HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert ctx.ltk_sc == bytes(range(7)) + b"\x00" * 9, \
        "SC ltk_sc must be reduced to the negotiated key size"


@pytest.mark.asyncio
async def test_distributed_ltk_reduced_to_negotiated_key_size(monkeypatch):
    """The LTK distributed in phase 3 (and stored in the bond for the
    Lower Tester's re-encryption) must honour the negotiated key size too —
    EKS/BV-02 step 6 re-encrypts with the distributed LTK."""
    import os

    from pybluehost.ble.smp import (
        SMPEvent, SMPCrypto, SMPPairingConfirm, SMPPairingRandom,
        SMPPairingRequest,
    )

    monkeypatch.setattr(SMPCrypto, "c1", staticmethod(lambda *a, **kw: b"\x44" * 16))
    monkeypatch.setattr(SMPCrypto, "s1", staticmethod(lambda *a, **kw: b"\x77" * 16))
    monkeypatch.setattr(os, "urandom", lambda n: b"\xAA" * n)

    mgr, sent = _make_manager()
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT, oob_data_flag=0,
        auth_req=0x01, max_key_size=7,
        init_key_dist=0x01, resp_key_dist=0x01,
    ).to_bytes(), connection_handle=HANDLE)
    await mgr.on_pdu(SMPPairingConfirm(confirm_value=b"\x44" * 16).to_bytes(),
                     connection_handle=HANDLE)
    await mgr.on_pdu(SMPPairingRandom(random_value=b"\x55" * 16).to_bytes(),
                     connection_handle=HANDLE)
    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    await ctx.state_machine.fire(SMPEvent.ENCRYPTION_CHANGE_SUCCESS)

    enc_info = next(p for p in sent if p[0] == SMPCode.ENCRYPTION_INFORMATION)
    ltk = enc_info[1:]
    assert ltk == b"\xAA" * 7 + b"\x00" * 9, \
        "distributed LTK must be reduced to the negotiated key size"
    assert ctx.local_ltk == b"\xAA" * 7 + b"\x00" * 9, \
        "the bond-stored local_ltk must match the distributed (reduced) LTK"


@pytest.mark.asyncio
async def test_configured_min_key_size_16_rejects_sc_short_keys():
    """GAP/SEC/SEM/BI-09/20/21/22/23 model "LE security mode 1 level 3/4": the
    IUT is configured with a 16-octet minimum, so ANY shorter SC key size in
    [7,15] must be rejected with Pairing Failed 0x06."""
    from pybluehost.ble.smp import SMPPairingRequest

    mgr, sent = _make_manager()
    mgr._security_config.min_encryption_key_size = 16

    for ks in (7, 12, 15):
        sent.clear()
        req = SMPPairingRequest(
            io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
            auth_req=0x0D, max_key_size=ks,
            init_key_dist=0x07, resp_key_dist=0x07,
        )
        await mgr.on_pdu(req.to_bytes(), connection_handle=HANDLE)
        assert sent and sent[-1][0] == SMPCode.PAIRING_FAILED, f"ks={ks}"
        assert sent[-1][1] == 0x06, f"ks={ks}"
        # Drop the failed context so the next round starts clean.
        mgr._contexts.pop(HANDLE, None)
        mgr.bind_channel(connection_handle=HANDLE, send=sent.append,
                         peer_address=PEER_ADDR)


@pytest.mark.asyncio
async def test_default_min_key_size_still_accepts_seven():
    """The default stays at the 7-octet Core floor — the GATT/SR key-size
    preambles deliberately pair with SC + a short key and must succeed, so this
    must NOT become an unconditional "SC implies 16" rule."""
    from pybluehost.ble.smp import SMPPairingRequest

    mgr, sent = _make_manager()
    req = SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
        auth_req=0x0D, max_key_size=7,
        init_key_dist=0x07, resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=HANDLE)

    assert sent and sent[-1][0] != SMPCode.PAIRING_FAILED
