"""End-to-end BTP GAP session — TCP client → BtpTester → GapService → IutActions → virtual stack."""
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
from pybluehost.stack import Stack


async def _read_frame(reader):
    header = await reader.readexactly(BTP_HEADER_SIZE)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


async def test_btp_gap_read_controller_info_via_bridge(unused_tcp_port):
    """e2e: TCP client asks GAP service for Controller Info via the bridge."""
    stack = await Stack.virtual()
    try:
        actions = IutActions(stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester)
        reg.register(gap)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)  # READY

                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GAP,
                    opcode=op.OP_GAP_READ_CONTROLLER_INFO,
                    controller_index=0, data=b"",
                )))
                await writer.drain()
                resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert resp.service == op.SERVICE_GAP
                assert resp.opcode == op.OP_STATUS_RESPONSE
                assert resp.data[0] == op.BTP_STATUS_SUCCESS
                # Payload: [status][6 BD_ADDR][4 supported][4 current][3 CoD][249 name][11 short]
                assert len(resp.data) >= 1 + 6 + 4 + 4
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        await stack.close()


async def test_btp_gap_set_powered_via_bridge(unused_tcp_port):
    """e2e: Set Powered command flips current_settings bit 0 in the response."""
    stack = await Stack.virtual()
    try:
        actions = IutActions(stack)
        reg = BtpServiceRegistry()
        reg.register(CoreService(registry=reg))
        tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
        gap = GapService(actions=actions, tester=tester)
        reg.register(gap)
        await tester.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
            try:
                await asyncio.wait_for(_read_frame(reader), timeout=1.0)  # READY

                writer.write(encode_btp_frame(BtpFrame(
                    service=op.SERVICE_GAP,
                    opcode=op.OP_GAP_SET_POWERED,
                    controller_index=0, data=bytes([1]),
                )))
                await writer.drain()
                resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
                assert resp.data[0] == op.BTP_STATUS_SUCCESS
                settings = int.from_bytes(resp.data[1:5], "little")
                assert settings & 0x01    # powered bit 0
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await tester.stop()
    finally:
        await stack.close()
