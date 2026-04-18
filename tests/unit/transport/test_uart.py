import asyncio

import pytest

from pybluehost.transport.uart import UARTTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_transport_data(self, data: bytes) -> None:
        self.received.append(data)


class _FakeWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.fixture
async def fake_serial(monkeypatch):
    """Monkeypatch serial_asyncio.open_serial_connection to return controllable streams."""
    reader = asyncio.StreamReader()
    writer = _FakeWriter()

    async def fake_open_serial_connection(**kwargs):
        return reader, writer

    import serial_asyncio  # imported here so the import in uart.py resolves first

    monkeypatch.setattr(
        serial_asyncio, "open_serial_connection", fake_open_serial_connection
    )
    return reader, writer


class TestUARTTransport:
    @pytest.mark.asyncio
    async def test_open_sets_is_open(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_send_writes_to_serial(self, fake_serial):
        _, writer = fake_serial
        t = UARTTransport("/dev/ttyUSB0", 115200)
        await t.open()
        await t.send(b"\x01\x03\x0c\x00")
        assert writer.written == [b"\x01\x03\x0c\x00"]
        await t.close()

    @pytest.mark.asyncio
    async def test_received_bytes_become_packets(self, fake_serial):
        reader, _ = fake_serial
        sink = _Collect()
        t = UARTTransport("/dev/ttyUSB0", 115200)
        t.set_sink(sink)
        await t.open()
        reader.feed_data(bytes.fromhex("01030c00040e0401030c00"))
        # Let the read loop run
        for _ in range(5):
            await asyncio.sleep(0)
        await t.close()
        assert sink.received == [
            bytes.fromhex("01030c00"),
            bytes.fromhex("040e0401030c00"),
        ]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        with pytest.raises(RuntimeError, match="not open"):
            await t.send(b"X")

    @pytest.mark.asyncio
    async def test_info(self, fake_serial):
        t = UARTTransport("/dev/ttyUSB0", 115200)
        info = t.info
        assert info.type == "uart"
        assert info.details["port"] == "/dev/ttyUSB0"
        assert info.details["baudrate"] == 115200

    @pytest.mark.asyncio
    async def test_read_loop_error_notifies_sink(self, fake_serial):
        reader, _ = fake_serial
        errors = []

        class ErrSink:
            async def on_transport_data(self, data: bytes) -> None:
                pass
            async def on_transport_error(self, error) -> None:
                errors.append(error)

        t = UARTTransport("/dev/ttyUSB0", 115200)
        t.set_sink(ErrSink())
        await t.open()
        # Feed invalid H4 data to trigger framer ValueError
        reader.feed_data(b"\xff\x00\x00")
        for _ in range(10):
            if errors:
                break
            await asyncio.sleep(0.01)
        await t.close()
        assert len(errors) == 1
        assert "H4" in str(errors[0]) or "indicator" in str(errors[0]).lower()
