"""E2E: K-frame violations over a real VirtualLELink must tear the channel down.

Mirrors PTS L2CAP/LE/CFC/BV-26/27/28: the peer (PTS role = central here sends,
IUT listens) delivers an illegal K-frame — SDU length > MTU, information
payload > MPS, or segments overrunning the declared SDU length — and the IUT
must answer with an L2CAP_DISCONNECTION_REQUEST for that channel.
"""
from __future__ import annotations

import asyncio
import struct

import pytest
import pytest_asyncio

from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH
from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.l2cap.channel import SimpleChannelEvents


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def viol_pair(stack, peer_stack, transport_mode):
    """IUT (peripheral role, listening) ↔ violator (central, sends bad frames)."""
    if transport_mode != "virtual":
        pytest.skip("violation e2e runs on virtual transport only")
    link = VirtualLELink(
        central=stack._virtual_controller,
        peripheral=peer_stack._virtual_controller,
        central_address=stack._local_address,
        peripheral_address=peer_stack._local_address,
    )
    try:
        c_handle = await link.connect()
        await asyncio.sleep(0.05)
        p_handle = list(peer_stack.l2cap._connections.keys())[0]
        # IUT listens; violator connects a channel to it.
        inbound: dict = {}

        def on_incoming(ch):
            inbound["channel"] = ch

        peer_stack.l2cap.listen_le_coc_channel(psm=0x0080, handler=on_incoming)
        c_ch = await stack.l2cap.connect_le_coc_channel(
            handle=c_handle, psm=0x0080,
            mtu=512, mps=247, initial_credits=10, timeout=2.0,
        )
        for _ in range(50):
            if "channel" in inbound:
                break
            await asyncio.sleep(0.01)
        assert "channel" in inbound
        yield stack, peer_stack, c_handle, p_handle, c_ch, inbound["channel"]
    finally:
        try:
            await link.disconnect()
        except Exception:
            pass


async def _send_raw_kframe(central, c_handle, peer_cid: int, payload: bytes):
    """Send a raw L2CAP K-frame from the central (violator) side."""
    l2cap_pdu = struct.pack("<HH", len(payload), peer_cid) + payload
    await central._hci.send_acl_data(c_handle, ACL_PB_FIRST_AUTO_FLUSH, l2cap_pdu)


async def _wait_disconnected(iut, p_ch, timeout=2.0):
    """Poll until the IUT tore the channel down locally (violation handled)."""
    for _ in range(int(timeout / 0.02)):
        if p_ch.cid not in iut.l2cap._le_channels:
            return True
        await asyncio.sleep(0.02)
    return False


async def test_sdu_length_over_mtu_disconnects(viol_pair):
    central, iut, c_handle, p_handle, c_ch, p_ch = viol_pair
    # IUT-side negotiated MTU = min(512, 512) = 512. Violate: SDU len = 600.
    await _send_raw_kframe(
        central, c_handle, p_ch.cid,
        (600).to_bytes(2, "little") + b"v" * 100,
    )
    assert await _wait_disconnected(iut, p_ch), "IUT kept channel open after SDU>MTU"


async def test_payload_over_mps_disconnects(viol_pair):
    central, iut, c_handle, p_handle, c_ch, p_ch = viol_pair
    # IUT-side negotiated MPS = 247. Violate: single K-frame payload of 300.
    await _send_raw_kframe(
        central, c_handle, p_ch.cid,
        (10).to_bytes(2, "little") + b"v" * 298,
    )
    assert await _wait_disconnected(iut, p_ch), "IUT kept channel open after payload>MPS"


async def test_segments_overrun_declared_sdu_disconnects(viol_pair):
    central, iut, c_handle, p_handle, c_ch, p_ch = viol_pair
    # First K-frame declares SDU = 5, carries 3 bytes.
    await _send_raw_kframe(
        central, c_handle, p_ch.cid,
        (5).to_bytes(2, "little") + b"abc",
    )
    await asyncio.sleep(0.02)
    # Continuation delivers 4 more bytes → 7 > 5 declared.
    await _send_raw_kframe(central, c_handle, p_ch.cid, b"defg")
    assert await _wait_disconnected(iut, p_ch), "IUT kept channel open after overrun"


async def test_legal_segmented_sdu_survives(viol_pair):
    """Guard: legal multi-segment SDU must NOT be torn down (BV regression)."""
    central, iut, c_handle, p_handle, c_ch, p_ch = viol_pair
    got: list = []
    p_ch.set_events(SimpleChannelEvents(on_data=lambda d: got.append(bytes(d))))
    await _send_raw_kframe(
        central, c_handle, p_ch.cid,
        (12).to_bytes(2, "little") + b"abc",
    )
    await _send_raw_kframe(central, c_handle, p_ch.cid, b"defghijkl")
    for _ in range(50):
        if got:
            break
        await asyncio.sleep(0.01)
    assert got == [b"abcdefghijkl"]
    assert p_ch.cid in iut.l2cap._le_channels, "channel torn down on legal SDU"
