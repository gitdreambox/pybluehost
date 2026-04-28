import asyncio
import struct
import pytest
from pybluehost.l2cap.manager import L2CAPManager
from pybluehost.l2cap.classic import ClassicChannel
from pybluehost.l2cap.constants import (
    CID_ATT,
    CID_CLASSIC_SIGNALING,
    CID_LE_SIGNALING,
    CID_SMP,
    PSM_SDP,
    PSM_RFCOMM,
    SignalingCode,
)
from pybluehost.l2cap.channel import ChannelState, SimpleChannelEvents
from pybluehost.l2cap.signaling import SignalingPacket, decode_signaling, encode_signaling
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


async def test_connect_classic_channel_opens_dynamic_channel(manager):
    m, hci = manager
    await m.on_connection(handle=0x0042, link_type=LinkType.ACL,
                          peer_address=None, role=None)

    connect_task = asyncio.create_task(
        m.connect_classic_channel(handle=0x0042, psm=PSM_SDP)
    )
    await asyncio.sleep(0)

    assert len(hci.sent) == 1
    _handle, _pb, l2cap_pdu = hci.sent[0]
    length, cid = struct.unpack_from("<HH", l2cap_pdu)
    assert cid == CID_CLASSIC_SIGNALING
    request = decode_signaling(l2cap_pdu[4:4 + length])
    assert request.code == SignalingCode.CONNECTION_REQUEST
    psm, source_cid = struct.unpack_from("<HH", request.data)
    assert psm == PSM_SDP
    assert source_cid == 0x0040

    conn_rsp = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONNECTION_RESPONSE,
            identifier=request.identifier,
            data=struct.pack("<HHHH", 0x0041, source_cid, 0x0000, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(conn_rsp), CID_CLASSIC_SIGNALING) + conn_rsp,
        )
    )
    for _ in range(10):
        if len(hci.sent) >= 2:
            break
        await asyncio.sleep(0.01)

    assert len(hci.sent) == 2
    config_pdu = hci.sent[1][2]
    config = decode_signaling(config_pdu[4:])
    assert config.code == SignalingCode.CONFIGURE_REQUEST
    dest_cid, flags = struct.unpack_from("<HH", config.data)
    assert dest_cid == 0x0041
    assert flags == 0

    config_rsp = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONFIGURE_RESPONSE,
            identifier=config.identifier,
            data=struct.pack("<HHH", source_cid, 0x0000, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(config_rsp), CID_CLASSIC_SIGNALING) + config_rsp,
        )
    )

    channel = await asyncio.wait_for(connect_task, timeout=0.5)
    assert isinstance(channel, ClassicChannel)
    assert channel.cid == source_cid
    assert channel.state == ChannelState.OPEN
    assert m.get_fixed_channel(0x0042, source_cid) is channel


async def test_connect_classic_channel_waits_through_pending_response(manager):
    m, hci = manager
    await m.on_connection(handle=0x0042, link_type=LinkType.ACL,
                          peer_address=None, role=None)

    connect_task = asyncio.create_task(
        m.connect_classic_channel(handle=0x0042, psm=PSM_SDP)
    )
    await asyncio.sleep(0)

    request = decode_signaling(hci.sent[0][2][4:])
    _psm, source_cid = struct.unpack_from("<HH", request.data)
    pending_rsp = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONNECTION_RESPONSE,
            identifier=request.identifier,
            data=struct.pack("<HHHH", 0x0041, source_cid, 0x0001, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(pending_rsp), CID_CLASSIC_SIGNALING) + pending_rsp,
        )
    )
    await asyncio.sleep(0.01)

    assert not connect_task.done()
    assert len(hci.sent) == 1

    success_rsp = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONNECTION_RESPONSE,
            identifier=request.identifier,
            data=struct.pack("<HHHH", 0x0041, source_cid, 0x0000, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(success_rsp), CID_CLASSIC_SIGNALING) + success_rsp,
        )
    )
    for _ in range(10):
        if len(hci.sent) >= 2:
            break
        await asyncio.sleep(0.01)

    config = decode_signaling(hci.sent[1][2][4:])
    config_rsp = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONFIGURE_RESPONSE,
            identifier=config.identifier,
            data=struct.pack("<HHH", source_cid, 0x0000, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(config_rsp), CID_CLASSIC_SIGNALING) + config_rsp,
        )
    )

    channel = await asyncio.wait_for(connect_task, timeout=0.5)
    assert channel.state == ChannelState.OPEN


async def test_listen_classic_channel_accepts_incoming_connection(manager):
    m, hci = manager
    await m.on_connection(handle=0x0042, link_type=LinkType.ACL,
                          peer_address=None, role=None)
    accepted = []

    async def on_channel(channel):
        accepted.append(channel)

    m.listen_classic_channel(psm=PSM_RFCOMM, handler=on_channel)
    request = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONNECTION_REQUEST,
            identifier=0x33,
            data=struct.pack("<HH", PSM_RFCOMM, 0x0041),
        )
    )

    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(request), CID_CLASSIC_SIGNALING) + request,
        )
    )

    assert len(hci.sent) == 2
    response = decode_signaling(hci.sent[0][2][4:])
    assert response.code == SignalingCode.CONNECTION_RESPONSE
    dest_cid, source_cid, result, status = struct.unpack_from("<HHHH", response.data)
    assert dest_cid == 0x0040
    assert source_cid == 0x0041
    assert result == 0
    assert status == 0
    local_config = decode_signaling(hci.sent[1][2][4:])
    assert local_config.code == SignalingCode.CONFIGURE_REQUEST
    assert struct.unpack_from("<HH", local_config.data) == (0x0041, 0x0000)

    config = encode_signaling(
        SignalingPacket(
            code=SignalingCode.CONFIGURE_REQUEST,
            identifier=0x34,
            data=struct.pack("<HH", dest_cid, 0x0000),
        )
    )
    await m.on_acl_data(
        HCIACLData(
            handle=0x0042,
            pb_flag=ACL_PB_FIRST_AUTO_FLUSH,
            data=struct.pack("<HH", len(config), CID_CLASSIC_SIGNALING) + config,
        )
    )

    assert len(hci.sent) == 3
    config_response = decode_signaling(hci.sent[2][2][4:])
    assert config_response.code == SignalingCode.CONFIGURE_RESPONSE
    assert struct.unpack_from("<HHH", config_response.data) == (0x0041, 0x0000, 0x0000)
    assert len(accepted) == 1
    assert accepted[0].cid == dest_cid
    assert accepted[0].state == ChannelState.OPEN
