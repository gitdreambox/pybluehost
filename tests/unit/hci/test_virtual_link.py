"""Two VirtualControllers paired as Central/Peripheral via VirtualLELink."""
from __future__ import annotations

import asyncio

from pybluehost.core.address import BDAddress
from pybluehost.hci.controller import HCIController
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.virtual_link import VirtualLELink


async def test_link_emits_connection_complete_to_both_sides():
    vc_a, host_a = await VirtualController.create()
    vc_b, host_b = await VirtualController.create()
    hci_a = HCIController(transport=host_a, trace=None, command_timeout=5.0)
    hci_b = HCIController(transport=host_b, trace=None, command_timeout=5.0)
    await hci_a.initialize()
    await hci_b.initialize()

    seen_a: list[int] = []
    seen_b: list[int] = []

    async def _track_a(event):
        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event
        if isinstance(event, HCI_LE_Meta_Event) and event.subevent_code == LEMetaSubEvent.LE_CONNECTION_COMPLETE:
            handle = int.from_bytes(event.subevent_parameters[1:3], "little")
            seen_a.append(handle)

    async def _track_b(event):
        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event
        if isinstance(event, HCI_LE_Meta_Event) and event.subevent_code == LEMetaSubEvent.LE_CONNECTION_COMPLETE:
            handle = int.from_bytes(event.subevent_parameters[1:3], "little")
            seen_b.append(handle)

    hci_a.set_upstream(on_hci_event=_track_a, on_acl_data=lambda _: None)
    hci_b.set_upstream(on_hci_event=_track_b, on_acl_data=lambda _: None)

    link = VirtualLELink(
        central=vc_a, peripheral=vc_b,
        central_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        peripheral_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"),
    )
    handle = await link.connect()
    await asyncio.sleep(0.1)
    assert seen_a == [handle]
    assert seen_b == [handle]

    await host_a.close()
    await host_b.close()


async def test_link_forwards_acl_data_bidirectionally():
    vc_a, host_a = await VirtualController.create()
    vc_b, host_b = await VirtualController.create()
    hci_a = HCIController(transport=host_a, trace=None, command_timeout=5.0)
    hci_b = HCIController(transport=host_b, trace=None, command_timeout=5.0)
    await hci_a.initialize()
    await hci_b.initialize()

    rx_a: list[bytes] = []
    rx_b: list[bytes] = []

    async def _on_acl_a(acl):
        rx_a.append(bytes(acl.data))

    async def _on_acl_b(acl):
        rx_b.append(bytes(acl.data))

    hci_a.set_upstream(on_hci_event=lambda _e: None, on_acl_data=_on_acl_a)
    hci_b.set_upstream(on_hci_event=lambda _e: None, on_acl_data=_on_acl_b)

    link = VirtualLELink(
        central=vc_a, peripheral=vc_b,
        central_address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        peripheral_address=BDAddress(b"\x0A\x0B\x0C\x0D\x0E\x0F"),
    )
    handle = await link.connect()
    await asyncio.sleep(0.05)

    # Central sends — Peripheral receives
    await hci_a.send_acl_data(handle=handle, pb_flag=0, data=b"hello")
    await asyncio.sleep(0.05)
    assert rx_b == [b"hello"]

    # Peripheral sends — Central receives
    await hci_b.send_acl_data(handle=handle, pb_flag=0, data=b"world")
    await asyncio.sleep(0.05)
    assert rx_a == [b"world"]

    await host_a.close()
    await host_b.close()
