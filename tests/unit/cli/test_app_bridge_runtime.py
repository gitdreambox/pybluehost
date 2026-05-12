import argparse
import asyncio
import importlib.util
import struct

import pytest

from pybluehost.cli.app.bridge import HCITransportBridge, _run_bridge_command
from pybluehost.transport.base import Transport, TransportInfo


class RecordingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True
        self.opened = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    @property
    def is_open(self) -> bool:
        return self.opened

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="test",
            description="recording transport",
            platform="test",
            details={},
        )

    async def emit(self, data: bytes) -> None:
        assert self._sink is not None
        await self._sink.on_transport_data(data)


async def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(0.01)


def test_transport_package_does_not_export_cli_bridge():
    import pybluehost.transport as transport

    assert "HCITransportBridge" not in transport.__all__
    assert not hasattr(transport, "HCITransportBridge")
    assert importlib.util.find_spec("pybluehost.transport.bridge") is None


@pytest.mark.asyncio
async def test_tcp_bridge_reassembles_frontend_stream_and_writes_backend():
    backend = RecordingTransport()
    bridge = HCITransportBridge(backend, protocol="tcp", host="127.0.0.1", port=0)
    await bridge.start()
    try:
        host, port = bridge.listen_addr
        reader, writer = await asyncio.open_connection(host, port)
        packet = bytes.fromhex("01 03 0c 00")

        writer.write(packet[:2])
        await writer.drain()
        await asyncio.sleep(0.02)
        assert backend.sent == []

        writer.write(packet[2:])
        await writer.drain()
        await _wait_for(lambda: backend.sent == [packet])

        response = bytes.fromhex("04 0e 04 01 03 0c 00")
        await backend.emit(response)
        assert await reader.readexactly(len(response)) == response

        writer.close()
        await writer.wait_closed()
    finally:
        await bridge.close()

    assert backend.closed is True


@pytest.mark.asyncio
async def test_udp_bridge_forwards_one_hci_packet_per_datagram():
    backend = RecordingTransport()
    bridge = HCITransportBridge(backend, protocol="udp", host="127.0.0.1", port=0)
    await bridge.start()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    class Client(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            queue.put_nowait(data)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        Client,
        local_addr=("127.0.0.1", 0),
        remote_addr=bridge.listen_addr,
    )
    try:
        packet = bytes.fromhex("01 03 0c 00")
        transport.sendto(packet)
        await _wait_for(lambda: backend.sent == [packet])

        response = bytes.fromhex("04 0e 04 01 03 0c 00")
        await backend.emit(response)
        assert await asyncio.wait_for(queue.get(), timeout=1.0) == response
    finally:
        transport.close()
        await bridge.close()


@pytest.mark.asyncio
async def test_bridge_writes_btsnoop_packets(tmp_path):
    backend = RecordingTransport()
    path = tmp_path / "bridge.cfa"
    bridge = HCITransportBridge(
        backend,
        protocol="tcp",
        host="127.0.0.1",
        port=0,
        btsnoop=path,
    )
    await bridge.start()
    try:
        host, port = bridge.listen_addr
        reader, writer = await asyncio.open_connection(host, port)

        command = bytes.fromhex("01 03 0c 00")
        event = bytes.fromhex("04 0e 04 01 03 0c 00")
        writer.write(command)
        await writer.drain()
        await _wait_for(lambda: backend.sent == [command])

        await backend.emit(event)
        assert await reader.readexactly(len(event)) == event

        writer.close()
        await writer.wait_closed()
    finally:
        await bridge.close()

    data = path.read_bytes()
    assert data[:16] == b"btsnoop\x00" + struct.pack(">II", 1, 1002)
    first_record = data[16 : 16 + 24 + len(command)]
    second_record = data[16 + 24 + len(command) :]
    assert struct.unpack(">II", first_record[:8]) == (len(command), len(command))
    assert struct.unpack(">I", first_record[8:12])[0] == 0
    assert first_record[24:] == command
    assert struct.unpack(">II", second_record[:8]) == (len(event), len(event))
    assert struct.unpack(">I", second_record[8:12])[0] == 1
    assert second_record[24:] == event


@pytest.mark.asyncio
async def test_run_bridge_command_converts_cancellation_to_sigint_exit_code(monkeypatch):
    backend = RecordingTransport()

    async def parse_transport(_transport_arg):
        return backend

    monkeypatch.setattr("pybluehost.cli.app.bridge.parse_transport_arg", parse_transport)

    args = argparse.Namespace(
        transport="usb",
        protocol="tcp",
        host="127.0.0.1",
        port=0,
        hci_log=False,
        btsnoop=None,
    )
    task = asyncio.create_task(_run_bridge_command(args))
    await _wait_for(lambda: backend.opened)

    task.cancel()
    code = await asyncio.wait_for(task, timeout=2.0)

    assert code == 130
    assert backend.closed is True
