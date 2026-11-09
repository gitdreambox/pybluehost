"""SMP hashes the address the link actually uses on air.

GAP/PRIV/CONN/BV-10-C: the Lower Tester connects to the IUT's resolvable
private address and computes its Secure Connections DHKey Check with the RPA it
saw in its own connection event. The controller never reports a host-programmed
random address back, so the Stack hands it to SMP per connection; hashing the
public identity instead makes the pairing fail as Pairing Failed 0x0B.
"""
from __future__ import annotations

import pytest

from pybluehost.ble._smp_state import _local_sc_address, _peer_sc_address
from pybluehost.ble.smp import (
    SMPManager,
    SMPPairingContext,
    SMPPairingRequest,
    SMPPairingResponse,
)
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
PEER = BDAddress.from_string("FC:9E:53:D5:8D:EB")
IDENTITY = BDAddress.from_string("A0:85:27:2F:60:15")
# Wire bytes as the controller reported them (display 70:DA:10:DB:5B:1A).
RPA = BDAddress.from_hci(bytes.fromhex("1a5bdb10da70"), type=AddressType.RANDOM)


def _manager() -> SMPManager:
    return SMPManager(
        local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT,
        bondable=True,
        local_address=IDENTITY,
    )


async def test_initiator_hashes_the_registered_random_address():
    async def send(data: bytes) -> None:
        pass

    mgr = _manager()
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    mgr.register_local_address(HANDLE, RPA)

    await mgr.start_initiator(HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert isinstance(ctx, SMPPairingContext)
    assert ctx.local_address == RPA
    # f5/f6 take the address little-endian followed by the address type byte.
    assert _local_sc_address(ctx) == RPA.to_hci() + b"\x01"
    assert _peer_sc_address(ctx) == PEER.to_hci() + b"\x00"


async def test_responder_hashes_the_registered_random_address():
    async def send(data: bytes) -> None:
        pass

    mgr = _manager()
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    mgr.register_local_address(HANDLE, RPA)

    req = SMPPairingRequest(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x09,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await mgr.on_pdu(req.to_bytes(), connection_handle=HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert ctx.local_address == RPA
    assert _local_sc_address(ctx) == RPA.to_hci() + b"\x01"


@pytest.mark.parametrize("initiator", [True, False])
@pytest.mark.parametrize("identity", [
    IDENTITY,
    BDAddress.from_string("C0:85:27:2F:60:15", type=AddressType.RANDOM),
])
async def test_phase3_distributes_identity_instead_of_link_rpa(initiator, identity):
    """The address hashed in phase 2 is temporary; the IdKey address is stable."""
    from pybluehost.ble._smp_state import _start_phase3

    sent = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(local_address=identity)
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    mgr.register_local_address(HANDLE, RPA)
    if initiator:
        await mgr.start_initiator(HANDLE)
    else:
        await mgr.on_pdu(SMPPairingRequest(
            io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
            oob_data_flag=0, auth_req=0x01, max_key_size=16,
            init_key_dist=0x02, resp_key_dist=0x02,
        ).to_bytes(), connection_handle=HANDLE)
    ctx = mgr.get_context(HANDLE)
    ctx.local_init_key_dist = ctx.peer_init_key_dist = 0x02
    ctx.local_resp_key_dist = ctx.peer_resp_key_dist = 0x02
    sent.clear()

    await _start_phase3(ctx)

    assert sent[0] == b"\x08" + mgr.local_irk
    assert sent[1] == bytes([0x09, int(identity.type)]) + identity.to_hci()
    # Fixing IdKey must not change the address used by c1/f5/f6.
    assert ctx.local_address == RPA
    assert _local_sc_address(ctx) == RPA.to_hci() + b"\x01"


async def test_unbinding_clears_the_per_connection_address():
    async def send(data: bytes) -> None:
        pass

    mgr = _manager()
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    mgr.register_local_address(HANDLE, RPA)
    mgr.unbind_channel(HANDLE)

    # The same controller handle is reused by the next connection; a stale RPA
    # must not leak into it.
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    await mgr.start_initiator(HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert ctx.local_address == IDENTITY


async def test_pairing_response_does_not_override_the_registered_address():
    """Only the per-connection registration moves the local address."""
    async def send(data: bytes) -> None:
        pass

    mgr = _manager()
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER)
    await mgr.start_initiator(HANDLE)

    rsp = SMPPairingResponse(
        io_capability=IOCapability.NO_INPUT_NO_OUTPUT,
        oob_data_flag=0,
        auth_req=0x09,
        max_key_size=16,
        init_key_dist=0x07,
        resp_key_dist=0x07,
    )
    await mgr.on_pdu(rsp.to_bytes(), connection_handle=HANDLE)

    ctx = mgr.get_context(HANDLE)
    assert ctx is not None
    assert ctx.local_address == IDENTITY
