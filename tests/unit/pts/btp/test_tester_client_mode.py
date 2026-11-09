"""BtpTester client mode — connect OUT to an auto-pts BTPSocketSrv.

auto-pts is the BTP *server* (it listens and accepts); the IUT must connect to
it. Client mode reuses the same frame codec + service dispatch as server mode,
only the transport direction differs.
"""
import asyncio

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BtpFrame, decode_btp_frame, encode_btp_frame,
)
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.core import CoreService
from pybluehost.pts.btp.tester import BtpTester


async def _read_frame(reader: asyncio.StreamReader) -> BtpFrame:
    header = await reader.readexactly(5)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


class _DummyAutoPtsServer:
    """Minimal stand-in for auto-pts BTPSocketSrv: accepts one conn, captures it."""

    def __init__(self) -> None:
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._server: asyncio.Server | None = None
        self._accepted = asyncio.Event()

    async def start(self, host: str, port: int) -> int:
        self._server = await asyncio.start_server(self._on_conn, host, port)
        return self._server.sockets[0].getsockname()[1]

    async def _on_conn(self, reader, writer):
        self.reader, self.writer = reader, writer
        self._accepted.set()

    async def wait_accepted(self, timeout=2.0):
        await asyncio.wait_for(self._accepted.wait(), timeout)

    async def stop(self):
        if self.writer is not None:
            self.writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def client_mode(unused_tcp_port):
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    server = _DummyAutoPtsServer()
    # Bind on an ephemeral port actually chosen by the OS.
    port = await server.start("127.0.0.1", 0)
    tester = BtpTester(registry=reg, connect_to=("127.0.0.1", port))
    await tester.start()
    await server.wait_accepted()
    yield tester, server
    await tester.stop()
    await server.stop()


async def test_client_mode_connects_and_emits_ready(client_mode):
    """In client mode the tester connects out and sends the READY event first."""
    _tester, server = client_mode
    first = await asyncio.wait_for(_read_frame(server.reader), timeout=2.0)
    assert first.service == op.SERVICE_CORE
    assert first.opcode == op.OP_CORE_EVENT_READY


async def test_client_mode_dispatches_command_and_responds(client_mode):
    """auto-pts (server side) sends a command; the client-mode tester answers."""
    _tester, server = client_mode
    # Drain READY
    await asyncio.wait_for(_read_frame(server.reader), timeout=2.0)

    server.writer.write(encode_btp_frame(BtpFrame(
        service=op.SERVICE_CORE,
        opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )))
    await server.writer.drain()

    response = await asyncio.wait_for(_read_frame(server.reader), timeout=2.0)
    assert response.service == op.SERVICE_CORE
    # auto-pts framing: success echoes the request opcode, payload is data-only.
    assert response.opcode == op.OP_CORE_READ_SUPPORTED_SERVICES
    assert response.data[0] & 0x01  # Core service bit set
