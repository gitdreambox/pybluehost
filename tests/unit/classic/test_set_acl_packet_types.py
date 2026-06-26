"""ClassicConnectionManager.set_acl_packet_types — request + event wait.

Stubs HCI so the timing-sensitive listener/timeout code can be exercised
without a real transport.
"""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.classic.gap import ClassicConnectionManager
from pybluehost.hci.constants import ClassicPacketType
from pybluehost.hci.packets import (
    ConnectionPacketTypeChanged,
    HCI_Change_Connection_Packet_Type,
)


class _StubHCI:
    def __init__(self):
        self.sent: list = []
        self._listeners: list = []
        self._connection_packet_type_changed_listeners = self._listeners

    async def send_command(self, cmd):
        self.sent.append(cmd)

    def on_connection_packet_type_changed(self, listener) -> None:
        self._listeners.append(listener)

    def fire(self, parsed: ConnectionPacketTypeChanged) -> None:
        for listener in list(self._listeners):
            listener(parsed)


@pytest.mark.asyncio
async def test_force_2dh_only_clears_br_and_sets_3dh_disallow():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)

    async def fire():
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0040,
            packet_type=ClassicPacketType.ALL_3DH_DISALLOW,
        ))

    asyncio.create_task(fire())
    result = await mgr.set_acl_packet_types(
        0x0040, allow_br=False, allow_2dh=True, allow_3dh=False,
    )
    sent = hci.sent[0]
    assert isinstance(sent, HCI_Change_Connection_Packet_Type)
    assert sent.connection_handle == 0x0040
    # Expected mask: 0 BR + ALL_3DH_DISALLOW (clear 2-DH bits = "allow 2-DH")
    assert sent.packet_type == ClassicPacketType.ALL_3DH_DISALLOW
    assert result.packet_type == ClassicPacketType.ALL_3DH_DISALLOW


@pytest.mark.asyncio
async def test_force_3dh_only_sets_2dh_disallow():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)

    async def fire():
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0040,
            packet_type=ClassicPacketType.ALL_2DH_DISALLOW,
        ))

    asyncio.create_task(fire())
    await mgr.set_acl_packet_types(
        0x0040, allow_br=False, allow_2dh=False, allow_3dh=True,
    )
    sent = hci.sent[0]
    # mask = ALL_2DH_DISALLOW = 0x1102
    assert sent.packet_type == ClassicPacketType.ALL_2DH_DISALLOW


@pytest.mark.asyncio
async def test_default_all_allowed_emits_br_mask_only():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)

    async def fire():
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0040,
            packet_type=ClassicPacketType.ALL_BR,
        ))

    asyncio.create_task(fire())
    await mgr.set_acl_packet_types(0x0040)
    sent = hci.sent[0]
    # Default: BR allowed (bits set), EDR not disallowed (no inversion bits)
    # → mask = ALL_BR
    assert sent.packet_type == ClassicPacketType.ALL_BR


@pytest.mark.asyncio
async def test_ignores_event_for_different_handle():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)

    async def fire_two():
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0099,
            packet_type=ClassicPacketType.ALL_BR,
        ))
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0040,
            packet_type=ClassicPacketType.ALL_3DH_DISALLOW,
        ))

    asyncio.create_task(fire_two())
    result = await mgr.set_acl_packet_types(
        0x0040, allow_br=False, allow_2dh=True, allow_3dh=False,
    )
    assert result.connection_handle == 0x0040


@pytest.mark.asyncio
async def test_times_out_when_event_never_arrives():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)
    with pytest.raises(asyncio.TimeoutError):
        await mgr.set_acl_packet_types(0x0040, timeout_s=0.05)


@pytest.mark.asyncio
async def test_cleans_up_listener_on_success_and_timeout():
    hci = _StubHCI()
    mgr = ClassicConnectionManager(hci)

    # Success path
    async def fire():
        await asyncio.sleep(0)
        hci.fire(ConnectionPacketTypeChanged(
            status=0, connection_handle=0x0040,
            packet_type=ClassicPacketType.ALL_BR,
        ))

    asyncio.create_task(fire())
    await mgr.set_acl_packet_types(0x0040)
    assert hci._listeners == []

    # Timeout path
    with pytest.raises(asyncio.TimeoutError):
        await mgr.set_acl_packet_types(0x0040, timeout_s=0.05)
    assert hci._listeners == []
