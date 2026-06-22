import asyncio

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BtpFrame, decode_btp_frame, encode_btp_frame,
)
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.core import CoreService
from pybluehost.pts.btp.tester import BtpTester


@pytest.fixture
async def running_tester(unused_tcp_port):
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
    await tester.start()
    yield tester, unused_tcp_port
    await tester.stop()


async def _read_frame(reader: asyncio.StreamReader) -> BtpFrame:
    header = await reader.readexactly(5)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


async def test_tester_responds_to_read_supported_services(running_tester):
    _tester, port = running_tester
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # Drain the unsolicited READY event first
        ready = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
        assert ready.opcode == op.OP_CORE_EVENT_READY

        writer.write(encode_btp_frame(BtpFrame(
            service=op.SERVICE_CORE,
            opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
            controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
        )))
        await writer.drain()
        response = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
        assert response.service == op.SERVICE_CORE
        assert response.opcode == op.OP_STATUS_RESPONSE
        assert response.data[0] == op.BTP_STATUS_SUCCESS
        # Core registered → bit 0 set in the bitfield byte after status.
        assert response.data[1] & 0x01
    finally:
        writer.close()
        await writer.wait_closed()


async def test_tester_responds_to_unknown_service_with_unknown_cmd(running_tester):
    _tester, port = running_tester
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # Drain READY
        await asyncio.wait_for(_read_frame(reader), timeout=1.0)

        writer.write(encode_btp_frame(BtpFrame(
            service=0xEE,       # not registered
            opcode=0x01,
            controller_index=0, data=b"",
        )))
        await writer.drain()
        response = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
        assert response.service == 0xEE
        assert response.opcode == op.OP_STATUS_RESPONSE
        assert response.data[0] == op.BTP_STATUS_UNKNOWN_CMD
    finally:
        writer.close()
        await writer.wait_closed()


async def test_tester_handles_two_back_to_back_commands(running_tester):
    _tester, port = running_tester
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await asyncio.wait_for(_read_frame(reader), timeout=1.0)  # READY

        for _ in range(2):
            writer.write(encode_btp_frame(BtpFrame(
                service=op.SERVICE_CORE,
                opcode=op.OP_CORE_READ_SUPPORTED_COMMANDS,
                controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
            )))
        await writer.drain()
        for _ in range(2):
            resp = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_SUCCESS
    finally:
        writer.close()
        await writer.wait_closed()


async def test_tester_emits_ready_event_on_connect(running_tester):
    """Core READY event is the first frame after accept."""
    _tester, port = running_tester
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        first = await asyncio.wait_for(_read_frame(reader), timeout=1.0)
        assert first.service == op.SERVICE_CORE
        assert first.opcode == op.OP_CORE_EVENT_READY
    finally:
        writer.close()
        await writer.wait_closed()
