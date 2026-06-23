"""End-to-end BTP L2CAP session — TCP client → BtpTester → LeCoCService → VirtualLELink.

A single autoptsclient calls Listen, then a second virtual stack initiates the
LE CoC connect through VirtualLELink. The IUT-side BTP service reports the
incoming channel via 0x81 Connected event."""
import asyncio

import pytest

from pybluehost.hci.virtual_link import VirtualLELink
from pybluehost.pts.actions import IutActions
from pybluehost.pts.btp import (
    BtpServiceRegistry, BtpTester, CoreService, opcodes as op,
)
from pybluehost.pts.btp.protocol import (
    BTP_HEADER_SIZE, BtpFrame, decode_btp_frame, encode_btp_frame,
)
from pybluehost.pts.btp.services.gap import GapService
from pybluehost.pts.btp.services.gatt import GattService
from pybluehost.pts.btp.services.l2cap import LeCoCService
from pybluehost.stack import Stack


async def _read_frame(reader):
    header = await reader.readexactly(BTP_HEADER_SIZE)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


async def test_btp_l2cap_listen_via_bridge(unused_tcp_port):
    """autoptsclient → Listen on PSM 0x0080 → SUCCESS."""
    stack = await Stack.virtual()
    try:
        actions = IutActions(stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester); reg.register(gap)
        gatt = GattService(actions=actions, tester=tester); reg.register(gatt)
        l2cap_svc = LeCoCService(actions=actions, tester=tester); reg.register(l2cap_svc)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)  # READY

                # Listen request — 9-byte body
                body = (
                    (0x0080).to_bytes(2, "little") + bytes([0])
                    + (512).to_bytes(2, "little") + bytes([0, 16])
                    + (0).to_bytes(2, "little")
                )
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_L2CAP, opcode=op.OP_L2CAP_LISTEN,
                    controller_index=0, data=body,
                )))
                await writer.drain()
                resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert resp.opcode == op.OP_STATUS_RESPONSE
                assert resp.data == bytes([op.BTP_STATUS_SUCCESS])
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        await stack.close()


async def test_btp_l2cap_incoming_connect_emits_event(unused_tcp_port):
    """Two virtual stacks paired via VirtualLELink. IUT-side Listen via BTP;
    peer initiates LE CoC connect; assert the BTP 0x81 Connected event."""
    iut_stack = await Stack.virtual()
    peer_stack = await Stack.virtual()
    link = VirtualLELink(
        central=peer_stack._virtual_controller,
        peripheral=iut_stack._virtual_controller,
        central_address=peer_stack._local_address,
        peripheral_address=iut_stack._local_address,
    )
    try:
        # Bring up the LE link first.
        await link.connect()
        await asyncio.sleep(0.05)
        iut_handle = next(iter(iut_stack.l2cap._connections.keys()))
        peer_handle = next(iter(peer_stack.l2cap._connections.keys()))

        # Wire up the IUT BTP stack.
        actions = IutActions(iut_stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester); reg.register(gap)
        gatt = GattService(actions=actions, tester=tester); reg.register(gatt)
        l2cap_svc = LeCoCService(actions=actions, tester=tester); reg.register(l2cap_svc)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)  # READY

                # autoptsclient: LISTEN
                body = (
                    (0x0080).to_bytes(2, "little") + bytes([0])
                    + (512).to_bytes(2, "little") + bytes([0, 16])
                    + (0).to_bytes(2, "little")
                )
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_L2CAP, opcode=op.OP_L2CAP_LISTEN,
                    controller_index=0, data=body,
                )))
                await writer.drain()
                resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert resp.data == bytes([op.BTP_STATUS_SUCCESS])

                # Now the peer initiates LE CoC connect to PSM 0x0080.
                ch = await peer_stack.l2cap.connect_le_coc_channel(
                    handle=peer_handle, psm=0x0080, timeout=2.0,
                )
                assert ch is not None

                # Expect the IUT-side BTP service to emit 0x81 Connected.
                evt = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert evt.service == op.SERVICE_L2CAP
                assert evt.opcode == op.OP_L2CAP_EVENT_CONNECTED
                # Payload: chan_id(1) + psm(2) + ... (18 bytes total)
                assert len(evt.data) == 18
                assert int.from_bytes(evt.data[1:3], "little") == 0x0080
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        try:
            await link.disconnect()
        except Exception:
            pass
        await iut_stack.close()
        await peer_stack.close()
