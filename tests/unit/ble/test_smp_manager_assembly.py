"""SMPManager assembly + Stack binding tests."""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
)
from pybluehost.core.address import BDAddress


async def test_smp_manager_responder_replies_to_pairing_request():
    """SMP Manager auto-creates Responder context on inbound Pairing Request."""
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager()
    mgr.bind_channel(
        connection_handle=0x0040,
        send=send,
        peer_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
    )

    # Pairing Request: opcode 0x01 + io/oob/auth/maxkey/initkd/respkd
    await mgr.on_pdu(b"\x01\x03\x00\x01\x10\x07\x07", connection_handle=0x0040)

    assert len(sent) == 1
    assert sent[0][0] == SMPCode.PAIRING_RESPONSE


async def test_stack_virtual_assembles_smp_manager():
    """Stack._build constructs SMPManager and exposes it on stack.smp."""
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    try:
        assert stack.smp is not None
        assert isinstance(stack.smp, SMPManager)
    finally:
        await stack.close()


async def test_stack_virtual_propagates_bond_storage_to_smp():
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.stack import Stack, StackConfig

    storage = JsonBondStorage(path=":memory:")
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        assert stack.smp._bond_storage is storage
    finally:
        await stack.close()


async def test_unified_gap_set_pairing_delegate_downstreams_to_smp():
    """gap.set_pairing_delegate must actually reach SMPManager."""
    from pybluehost.ble.smp import AutoAcceptDelegate
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    try:
        delegate = AutoAcceptDelegate()
        stack.gap.set_pairing_delegate(delegate)
        assert stack.smp._delegate is delegate
    finally:
        await stack.close()


async def test_stack_unbinds_smp_channel_on_le_disconnect():
    """LE disconnect must remove the SMP sender to avoid stale-handle leaks."""
    from pybluehost.core.types import LinkType
    from pybluehost.stack import Stack

    stack = await Stack.virtual()
    try:
        # Simulate L2CAP LE connection open + disconnect cycle
        await stack._l2cap.on_connection(
            handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None,
        )
        assert 0x0040 in stack.smp._senders

        await stack._l2cap.on_disconnection(handle=0x0040, reason=0x16)
        assert 0x0040 not in stack.smp._senders
    finally:
        await stack.close()
