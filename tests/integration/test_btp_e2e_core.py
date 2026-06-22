"""End-to-end BTP session test — TCP client → BtpTester → Core service.

Walks the upstream-aligned Core surface (LOG_MESSAGE + READ_BTP_MTU, no
RESET_BOARD — see plan banner)."""
import asyncio

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BtpFrame, decode_btp_frame, encode_btp_frame, BTP_HEADER_SIZE,
)
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.core import BTP_MTU, CoreService
from pybluehost.pts.btp.tester import BtpTester


async def _read_one_frame(reader: asyncio.StreamReader) -> BtpFrame:
    header = await reader.readexactly(BTP_HEADER_SIZE)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


async def _send_command(
    writer: asyncio.StreamWriter, *, service: int, opcode: int,
    controller_index: int = op.CONTROLLER_INDEX_NONE, data: bytes = b"",
) -> None:
    writer.write(encode_btp_frame(BtpFrame(
        service=service, opcode=opcode,
        controller_index=controller_index, data=data,
    )))
    await writer.drain()


async def test_btp_full_session_with_core_only(unused_tcp_port):
    """Walk the upstream Core surface: discovery + register failure + log + mtu."""
    reg = BtpServiceRegistry()
    reg.register(CoreService(registry=reg))
    tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
    await tester.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        try:
            # 1) READY event arrives unsolicited.
            ready = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert ready.service == op.SERVICE_CORE
            assert ready.opcode == op.OP_CORE_EVENT_READY

            # 2) Read Supported Services.
            await _send_command(
                writer, service=op.SERVICE_CORE,
                opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
            )
            resp = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_SUCCESS
            assert resp.data[1] & 0x01    # Core registered → bit 0 set

            # 3) Read Supported Commands.
            await _send_command(
                writer, service=op.SERVICE_CORE,
                opcode=op.OP_CORE_READ_SUPPORTED_COMMANDS,
            )
            resp = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_SUCCESS

            # 4) Register an unsupported service (GAP isn't registered) → FAILED.
            await _send_command(
                writer, service=op.SERVICE_CORE,
                opcode=op.OP_CORE_REGISTER,
                data=bytes([op.SERVICE_GAP]),
            )
            resp = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_FAILED

            # 5) LOG_MESSAGE (upstream-aligned; replaces obsolete RESET_BOARD step).
            await _send_command(
                writer, service=op.SERVICE_CORE,
                opcode=op.OP_CORE_LOG_MESSAGE,
                data=b"e2e test log line",
            )
            resp = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_SUCCESS

            # 6) READ_BTP_MTU.
            await _send_command(
                writer, service=op.SERVICE_CORE,
                opcode=op.OP_CORE_READ_BTP_MTU,
            )
            resp = await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)
            assert resp.data[0] == op.BTP_STATUS_SUCCESS
            assert int.from_bytes(resp.data[1:3], "little") == BTP_MTU
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await tester.stop()


async def test_btp_tester_handles_client_disconnect_cleanly(unused_tcp_port):
    """If the client disconnects mid-session, tester returns to listening."""
    reg = BtpServiceRegistry()
    reg.register(CoreService(registry=reg))
    tester = BtpTester(registry=reg, host="127.0.0.1", port=unused_tcp_port)
    await tester.start()
    try:
        # First client: connect, drain READY, disconnect.
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        await asyncio.wait_for(_read_one_frame(reader), timeout=1.0)  # READY
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
        # Second client: reconnect should also receive READY.
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        ready = await asyncio.wait_for(_read_one_frame(reader2), timeout=1.0)
        assert ready.opcode == op.OP_CORE_EVENT_READY
        writer2.close()
        await writer2.wait_closed()
    finally:
        await tester.stop()
