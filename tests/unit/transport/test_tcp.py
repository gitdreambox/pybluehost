import asyncio

import pytest
import pytest_asyncio

from pybluehost.transport.tcp import TCPTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


@pytest_asyncio.fixture
async def echo_server():
    """Local TCP echo: any bytes the client sends come back, and the server
    can also push extra bytes. Yields (host, port, push_fn)."""
    host = "127.0.0.1"
    push_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async def pump_pushes():
            while True:
                data = await push_queue.get()
                writer.write(data)
                await writer.drain()

        push_task = asyncio.create_task(pump_pushes())
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    return
                writer.write(data)
                await writer.drain()
        finally:
            push_task.cancel()
            try:
                await push_task
            except (asyncio.CancelledError, Exception):
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle, host, 0)
    port = server.sockets[0].getsockname()[1]

    async def push(data: bytes) -> None:
        await push_queue.put(data)

    try:
        yield host, port, push
    finally:
        server.close()
        await server.wait_closed()


class TestTCPTransport:
    @pytest.mark.asyncio
    async def test_open_close(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_is_echoed_and_reassembled(self, echo_server):
        host, port, _ = echo_server
        sink = _Collect()
        t = TCPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("01030c00")
        await t.send(packet)
        # wait for echo to come back via reader loop
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_fragmented_server_push_reassembled(self, echo_server):
        host, port, push = echo_server
        sink = _Collect()
        t = TCPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("040e0401030c00")
        await push(packet[:3])
        await push(packet[3:])
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, echo_server):
        host, port, _ = echo_server
        t = TCPTransport(host, port)
        assert t.info.type == "tcp"
        assert t.info.details["host"] == host
        assert t.info.details["port"] == port
