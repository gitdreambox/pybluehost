"""End-to-end BTP GATT session — TCP client → BtpTester → GattService → virtual stack."""
import asyncio

import pytest

from pybluehost.pts.actions import IutActions
from pybluehost.pts.btp import (
    BtpServiceRegistry, BtpTester, CoreService, opcodes as op,
)
from pybluehost.pts.btp.protocol import (
    BTP_HEADER_SIZE, BtpFrame, decode_btp_frame, encode_btp_frame,
)
from pybluehost.pts.btp.services.gap import GapService
from pybluehost.pts.btp.services.gatt import GattService
from pybluehost.stack import Stack


async def _read_frame(reader):
    header = await reader.readexactly(BTP_HEADER_SIZE)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


async def test_btp_gatt_add_service_via_bridge(unused_tcp_port):
    """e2e: TCP client adds a Battery Service via the BTP bridge; tester returns the handle."""
    stack = await Stack.virtual()
    try:
        actions = IutActions(stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester); reg.register(gap)
        gatt = GattService(actions=actions, tester=tester); reg.register(gatt)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)   # READY

                add_body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GATT, opcode=op.OP_GATT_ADD_SERVICE,
                    controller_index=0, data=add_body,
                )))
                await writer.drain()
                resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert resp.service == op.SERVICE_GATT
                assert resp.opcode == op.OP_STATUS_RESPONSE
                assert resp.data[0] == op.BTP_STATUS_SUCCESS
                handle = int.from_bytes(resp.data[1:3], "little")
                assert handle == 0x0001
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        await stack.close()


async def test_btp_gatt_set_value_emits_attr_changed_event(unused_tcp_port):
    """e2e: Add a characteristic, set its value, observe the 0x81 event."""
    stack = await Stack.virtual()
    try:
        actions = IutActions(stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester); reg.register(gap)
        gatt = GattService(actions=actions, tester=tester); reg.register(gatt)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)   # READY

                # Add Service
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GATT, opcode=op.OP_GATT_ADD_SERVICE,
                    controller_index=0,
                    data=bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18"),
                )))
                await writer.drain()
                svc_resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                svc_h = int.from_bytes(svc_resp.data[1:3], "little")

                # Add Characteristic
                char_body = (
                    svc_h.to_bytes(2, "little")
                    + bytes([op.GATT_CHRC_PROP_READ | op.GATT_CHRC_PROP_NOTIFY,
                             op.GATT_PERM_READ, 2])
                    + bytes.fromhex("1929")
                )
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GATT, opcode=op.OP_GATT_ADD_CHARACTERISTIC,
                    controller_index=0, data=char_body,
                )))
                await writer.drain()
                char_resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                char_h = int.from_bytes(char_resp.data[1:3], "little")

                # Set Value → triggers 0x81 event
                set_body = char_h.to_bytes(2, "little") + (1).to_bytes(2, "little") + b"\x55"
                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GATT, opcode=op.OP_GATT_SET_VALUE,
                    controller_index=0, data=set_body,
                )))
                await writer.drain()

                # Drain two frames: the SUCCESS response + the 0x81 event.
                # Order is not guaranteed (event fires via create_task) so collect both.
                frames = [
                    await asyncio.wait_for(_read_frame(reader), timeout=1.0),
                    await asyncio.wait_for(_read_frame(reader), timeout=1.0),
                ]
                ack = next(f for f in frames if f.opcode == op.OP_STATUS_RESPONSE)
                event = next(f for f in frames if f.opcode == op.OP_GATT_EVENT_ATTR_VALUE_CHANGED)
                assert ack.data[0] == op.BTP_STATUS_SUCCESS
                assert int.from_bytes(event.data[0:2], "little") == char_h
                assert int.from_bytes(event.data[2:4], "little") == 1
                assert event.data[4:5] == b"\x55"
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        await stack.close()
