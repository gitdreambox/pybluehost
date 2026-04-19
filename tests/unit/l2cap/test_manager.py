import asyncio
import struct
import pytest
from pybluehost.l2cap.manager import L2CAPManager
from pybluehost.l2cap.constants import CID_ATT, CID_SMP, CID_LE_SIGNALING, CID_CLASSIC_SIGNALING
from pybluehost.l2cap.channel import SimpleChannelEvents
from pybluehost.core.types import LinkType
from pybluehost.hci.packets import HCIACLData
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH


class FakeHCI:
    def __init__(self):
        self.sent: list[tuple[int, int, bytes]] = []

    async def send_acl_data(self, handle, pb_flag, data):
        self.sent.append((handle, pb_flag, data))


@pytest.fixture
def manager():
    hci = FakeHCI()
    m = L2CAPManager(hci=hci)
    return m, hci


async def test_on_le_connection_registers_att_smp(manager):
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)
    assert 0x0040 in m._connections
    assert CID_ATT in m._connections[0x0040]
    assert CID_SMP in m._connections[0x0040]
    assert CID_LE_SIGNALING in m._connections[0x0040]


async def test_on_classic_connection_registers_signaling(manager):
    m, hci = manager
    await m.on_connection(handle=0x0001, link_type=LinkType.ACL,
                          peer_address=None, role=None)
    assert CID_CLASSIC_SIGNALING in m._connections[0x0001]


async def test_acl_data_routes_to_fixed_channel(manager):
    m, hci = manager
    received = []

    async def on_data(data):
        received.append(data)

    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)
    ch = m.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    ch.set_events(SimpleChannelEvents(on_data=on_data))

    # Build ACL packet with L2CAP header
    payload = b"\x01\x02\x03"
    l2cap_pdu = struct.pack("<HH", len(payload), CID_ATT) + payload
    acl_pkt = HCIACLData(handle=0x0040, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=l2cap_pdu)
    await m.on_acl_data(acl_pkt)
    assert received == [payload]


async def test_on_disconnection_cleans_up(manager):
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)
    assert 0x0040 in m._connections
    await m.on_disconnection(handle=0x0040, reason=0x16)
    assert 0x0040 not in m._connections


async def test_get_fixed_channel_missing():
    m = L2CAPManager(hci=FakeHCI())
    assert m.get_fixed_channel(handle=0x9999, cid=CID_ATT) is None


async def test_acl_data_unknown_handle_ignored(manager):
    """Data for unknown handle should be silently dropped."""
    m, hci = manager
    payload = b"\x01"
    l2cap_pdu = struct.pack("<HH", len(payload), CID_ATT) + payload
    acl_pkt = HCIACLData(handle=0x9999, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=l2cap_pdu)
    await m.on_acl_data(acl_pkt)  # should not raise


async def test_acl_data_unknown_cid_ignored(manager):
    """Data for unknown CID should be silently dropped."""
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)
    payload = b"\x01"
    l2cap_pdu = struct.pack("<HH", len(payload), 0x00FF) + payload
    acl_pkt = HCIACLData(handle=0x0040, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=l2cap_pdu)
    await m.on_acl_data(acl_pkt)  # should not raise


async def test_on_disconnection_fires_on_close_callback(manager):
    """Disconnection should invoke on_close on channels that have events."""
    m, hci = manager
    close_reasons = []

    async def on_close(reason):
        close_reasons.append(reason)

    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)
    ch = m.get_fixed_channel(handle=0x0040, cid=CID_ATT)
    ch.set_events(SimpleChannelEvents(on_close=on_close))

    await m.on_disconnection(handle=0x0040, reason=0x13)
    assert close_reasons == [0x13]


async def test_register_channel(manager):
    """register_channel should add a dynamic channel to the connection."""
    m, hci = manager
    await m.on_connection(handle=0x0040, link_type=LinkType.LE,
                          peer_address=None, role=None)

    from pybluehost.l2cap.ble import FixedChannel
    fake_ch = FixedChannel(connection_handle=0x0040, cid=0x0040, hci=hci, mtu=512)
    m.register_channel(handle=0x0040, channel=fake_ch)
    assert m.get_fixed_channel(handle=0x0040, cid=0x0040) is fake_ch
