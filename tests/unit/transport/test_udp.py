import asyncio

import pytest
import pytest_asyncio

from pybluehost.transport.udp import UDPTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)


class _EchoServerProto(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        assert self.transport is not None
        self.transport.sendto(data, addr)


@pytest_asyncio.fixture
async def echo_udp_server():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        _EchoServerProto, local_addr=("127.0.0.1", 0)
    )
    host, port = transport.get_extra_info("sockname")
    try:
        yield host, port
    finally:
        transport.close()


class TestUDPTransport:
    @pytest.mark.asyncio
    async def test_open_close(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_datagram_echoed(self, echo_udp_server):
        host, port = echo_udp_server
        sink = _Collect()
        t = UDPTransport(host, port)
        t.set_sink(sink)
        await t.open()
        packet = bytes.fromhex("01030c00")
        await t.send(packet)
        for _ in range(20):
            if sink.received:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert sink.received == [packet]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, echo_udp_server):
        host, port = echo_udp_server
        t = UDPTransport(host, port)
        assert t.info.type == "udp"
        assert t.info.details["host"] == host
        assert t.info.details["port"] == port

    @pytest.mark.asyncio
    async def test_drain_error_notifies_sink(self, echo_udp_server):
        host, port = echo_udp_server
        errors = []

        class BrokenSink:
            async def on_data(self, data: bytes) -> None:
                raise RuntimeError("sink exploded")
            async def on_transport_error(self, error) -> None:
                errors.append(error)

        t = UDPTransport(host, port)
        t.set_sink(BrokenSink())
        await t.open()
        await t.send(b"\x01\x03\x0c\x00")
        for _ in range(20):
            if errors:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert len(errors) == 1
        assert "sink exploded" in str(errors[0])
