"""End-to-end LE CoC over VirtualLELink — listen + connect + send + disconnect.

Validates the LE Credit-Based Channel signaling path against two real
``Stack.virtual()`` instances bridged by ``VirtualLELink``.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from pybluehost.ble.att import ATT_Read_Request, ATT_Read_Response, decode_att_pdu
from pybluehost.ble.gatt import (
    CharacteristicDefinition, CharProperties, Permissions, ServiceDefinition,
)
from pybluehost.core.errors import LECoCConnectError
from pybluehost.core.uuid import UUID16
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.l2cap.channel import SimpleChannelEvents


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def le_pair(stack, peer_stack, transport_mode):
    """Two virtual stacks paired as central (stack) ↔ peripheral (peer_stack)."""
    if transport_mode != "virtual":
        pytest.skip("LE CoC e2e runs on virtual transport only")
    link = VirtualLELink(
        central=stack._virtual_controller,
        peripheral=peer_stack._virtual_controller,
        central_address=stack._local_address,
        peripheral_address=peer_stack._local_address,
    )
    try:
        c_handle = await link.connect()
        # Wait for both sides' L2CAPManager to register the connection via
        # LE_Connection_Complete.
        await asyncio.sleep(0.05)
        p_handles = list(peer_stack.l2cap._connections.keys())
        assert p_handles, "peer never registered an LE connection"
        p_handle = p_handles[0]
        yield stack, peer_stack, c_handle, p_handle
    finally:
        try:
            await link.disconnect()
        except Exception:
            pass


async def test_le_coc_connect_send_disconnect(le_pair):
    central, peripheral, c_handle, p_handle = le_pair

    # Peripheral listens on PSM 0x0080; record the incoming channel.
    inbound: dict = {}

    def on_incoming(ch):
        inbound["channel"] = ch
        inbound["received"] = []
        ch.set_events(SimpleChannelEvents(
            on_data=lambda data, ch=ch: inbound["received"].append(bytes(data)),
        ))

    peripheral.l2cap.listen_le_coc_channel(psm=0x0080, handler=on_incoming)

    # Central initiates connect.
    c_ch = await central.l2cap.connect_le_coc_channel(
        handle=c_handle, psm=0x0080,
        mtu=512, mps=247, initial_credits=10, timeout=2.0,
    )
    # Wait briefly for the peripheral-side channel object to be registered.
    for _ in range(20):
        if "channel" in inbound:
            break
        await asyncio.sleep(0.01)
    assert "channel" in inbound, "peripheral never received incoming channel"
    p_ch = inbound["channel"]

    # Send a small SDU from central → peripheral.
    await c_ch.send(b"hello")
    for _ in range(20):
        if inbound["received"]:
            break
        await asyncio.sleep(0.01)
    assert inbound["received"] == [b"hello"]

    # Disconnect from the central side.
    await central.l2cap.disconnect_le_coc_channel(c_ch)
    # Allow the peer to handle DISCONNECTION_REQUEST.
    await asyncio.sleep(0.05)
    # Both sides removed the channel.
    assert c_ch.cid not in central.l2cap._le_channels


async def test_eatt_bearers_answer_att_requests_over_virtual_link(le_pair):
    """Two EATT bearers over ECFC (SPSM 0x0027): both bearers carry ATT
    requests independently, each using the channel L2CAP MTU. The EATT
    listener requires an encrypted link, so mark the responder side encrypted
    (white-box: the security state is normally fed by HCI Encryption Change)."""
    central, peripheral, c_handle, p_handle = le_pair
    handles = peripheral.gatt_server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"AB" * 40,  # 80 bytes — fits EATT MTU, not MTU 23
                )
            ],
        )
    )
    value_handle = handles.characteristic_handles[0].value_handle
    peripheral.l2cap.set_le_connection_security(
        p_handle, encrypted=True, authenticated=True, key_size=16)

    channels = await central.l2cap.connect_eatt_channels(c_handle, num=2, timeout=2.0)
    assert len(channels) == 2

    for ch in channels:
        received: list[bytes] = []
        ch.set_events(SimpleChannelEvents(on_data=lambda d, r=received: r.append(bytes(d))))
        await ch.send(ATT_Read_Request(attribute_handle=value_handle).to_bytes())
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        assert received, "no ATT response on EATT bearer"
        rsp = decode_att_pdu(received[0])
        assert isinstance(rsp, ATT_Read_Response)
        # EATT bearer ATT_MTU is the channel L2CAP MTU (512): the whole
        # 80-byte value comes back — the fixed ATT channel would give 22
        # bytes of value (MTU 23 minus opcode).
        assert rsp.attribute_value == b"AB" * 40

    # Disconnect each bearer from the central side and verify both stacks
    # remove the channel objects.
    for ch in channels:
        await central.l2cap.disconnect_le_coc_channel(ch)
    await asyncio.sleep(0.05)
    for ch in channels:
        assert ch.cid not in central.l2cap._le_channels
        assert ch._peer_cid not in peripheral.l2cap._le_channels


async def test_eatt_connect_refused_on_unencrypted_link(le_pair):
    """Core Vol 3 Part G §5.2: EATT may only be established on an encrypted
    link — the listener refuses with 0x0008 (Insufficient Encryption)."""
    central, peripheral, c_handle, p_handle = le_pair
    with pytest.raises(LECoCConnectError) as exc_info:
        await central.l2cap.connect_eatt_channels(c_handle, num=1, timeout=2.0)
    assert exc_info.value.result == 0x0008
