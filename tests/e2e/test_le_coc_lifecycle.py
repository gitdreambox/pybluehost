"""End-to-end LE CoC over VirtualLELink — listen + connect + send + disconnect.

Validates the LE Credit-Based Channel signaling path against two real
``Stack.virtual()`` instances bridged by ``VirtualLELink``.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

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
