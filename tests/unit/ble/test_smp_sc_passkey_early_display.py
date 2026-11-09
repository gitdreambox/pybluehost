"""SC Passkey Entry: display must fire at feature-exchange time (SCPK/BI-03/BI-05).

PTS issues its "enter (wrong) passkey" MMI (WID 106) — and the positive WID 141
too — as soon as pairing starts, BEFORE the public-key exchange completes.
auto-pts computes the entry from ``stack.gap.passkey.data``, fed by our BTP
PASSKEY_DISPLAY event. Deferring the display until after the key exchange
(as before) loses that race: passkey.data is still None and WID 106 crashes
with ``int(None)`` (FATAL ERROR). The display must be emitted as soon as the
association model resolves (Pairing Request/Response time), and the later
``_sc_passkey_*_display_enter`` must not duplicate or replace it.
"""
from __future__ import annotations

import pytest

from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingPublicKey,
    SMPPairingRequest,
    SMPPairingResponse,
)
from pybluehost.ble.security import SecurityConfig
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
PEER = BDAddress(b"\x01\x02\x03\x04\x05\x06")


class _RecordingDelegate:
    """Delegate that records every display_passkey call."""

    def __init__(self) -> None:
        self.displayed: list[int] = []

    async def display_passkey(self, peer_addr, passkey: int) -> None:
        self.displayed.append(int(passkey))

    async def get_passkey(self, peer_addr) -> int:
        return 0

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, peer_addr, passkey: int) -> bool:
        return True

    async def confirm_numeric(self, peer_addr, value: int) -> bool:
        return True


def _manager(delegate) -> tuple[SMPManager, list[bytes]]:
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    cfg = SecurityConfig(enable_secure_connections=True, mitm_required=True)
    mgr = SMPManager(
        local_io_caps=IOCapability.DISPLAY_ONLY, bondable=True,
        security_config=cfg, delegate=delegate,
    )
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    return mgr, sent


@pytest.mark.asyncio
async def test_initiator_displays_passkey_at_feature_exchange():
    """SM/CEN/SCPK/BI-03: after the Pairing Response arrives (peer KeyboardOnly,
    MITM+SC), the passkey display must already have fired — before the peer's
    public key ever arrives."""
    delegate = _RecordingDelegate()
    mgr, sent = _manager(delegate)

    await mgr.start_initiator(HANDLE)
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.KEYBOARD_ONLY, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)

    assert delegate.displayed, "display_passkey must fire at feature exchange"
    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert getattr(ctx, "passkey", None) == delegate.displayed[0]


@pytest.mark.asyncio
async def test_initiator_display_not_duplicated_after_public_key():
    """After the peer's public key arrives, the display must not fire again nor
    change value; round-1 confirm is sent with the already-displayed passkey."""
    delegate = _RecordingDelegate()
    mgr, sent = _manager(delegate)

    await mgr.start_initiator(HANDLE)
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=IOCapability.KEYBOARD_ONLY, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    first = delegate.displayed[0]

    peer_pub = generate_p256_keypair()[1]
    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=peer_pub[:32], public_key_y=peer_pub[32:],
    ).to_bytes(), connection_handle=HANDLE)

    assert delegate.displayed == [first], "display must fire exactly once"
    assert sent[-1][0] == SMPCode.PAIRING_CONFIRM, "round-1 confirm must be sent"


@pytest.mark.asyncio
async def test_responder_displays_passkey_at_feature_exchange():
    """SM/PER/SCPK/BI-05: the responder learns the model from the Pairing
    Request; its display must fire when the response is sent, not later."""
    delegate = _RecordingDelegate()
    mgr, sent = _manager(delegate)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=IOCapability.KEYBOARD_ONLY, oob_data_flag=0,
        auth_req=0x0D, max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)

    assert sent and sent[0][0] == SMPCode.PAIRING_RESPONSE
    assert delegate.displayed, "responder display must fire at feature exchange"

    peer_pub = generate_p256_keypair()[1]
    await mgr.on_pdu(SMPPairingPublicKey(
        public_key_x=peer_pub[:32], public_key_y=peer_pub[32:],
    ).to_bytes(), connection_handle=HANDLE)
    assert len(delegate.displayed) == 1, "display must not be duplicated"
