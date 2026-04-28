"""Integration test: HCIController + L2CAPManager with VirtualController.

Verifies that the full HCI to L2CAP path works end-to-end without hardware.
"""
from __future__ import annotations

import struct

from pybluehost.core.types import LinkType
from pybluehost.hci.packets import HCIACLData
from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.l2cap.constants import CID_ATT, CID_SMP


async def test_l2cap_on_connection_registers_att_smp(stack):
    """After on_connection(LE), L2CAPManager has ATT and SMP fixed channels."""
    l2cap = stack.l2cap
    hci = stack.hci
    hci.set_upstream(
        on_hci_event=l2cap.on_hci_event,
        on_acl_data=l2cap.on_acl_data,
    )

    # Manually trigger LE connection (simulating what on_hci_event would do)
    await l2cap.on_connection(
        handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None
    )

    assert 0x0040 in l2cap._connections
    att_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    smp_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_SMP)
    assert att_ch is not None
    assert smp_ch is not None


async def test_l2cap_acl_routes_to_att_channel(stack):
    """ACL data with CID=ATT is routed to the ATT FixedChannel."""
    l2cap = stack.l2cap
    hci = stack.hci
    hci.set_upstream(
        on_hci_event=l2cap.on_hci_event,
        on_acl_data=l2cap.on_acl_data,
    )

    await l2cap.on_connection(
        handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None
    )

    received: list[bytes] = []

    async def on_data(data: bytes) -> None:
        received.append(data)

    att_ch = l2cap.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    att_ch.set_events(SimpleChannelEvents(on_data=on_data))

    # Build L2CAP PDU: header (len=3, CID=ATT) + payload
    payload = b"\x02\x17\x00"  # ATT Exchange MTU Request (opcode + mtu)
    l2cap_pdu = struct.pack("<HH", len(payload), CID_ATT) + payload

    # Inject as ACL data through controller's on_transport_data
    acl = HCIACLData(handle=0x0040, pb_flag=0x02, bc_flag=0x00, data=l2cap_pdu)
    await hci.on_transport_data(acl.to_bytes())

    assert received == [payload]


async def test_l2cap_disconnection_cleans_up(stack):
    """After disconnection, channels are cleaned up."""
    l2cap = stack.l2cap
    hci = stack.hci
    hci.set_upstream(
        on_hci_event=l2cap.on_hci_event,
        on_acl_data=l2cap.on_acl_data,
    )

    await l2cap.on_connection(
        handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None
    )
    assert 0x0040 in l2cap._connections

    await l2cap.on_disconnection(handle=0x0040, reason=0x16)
    assert 0x0040 not in l2cap._connections
