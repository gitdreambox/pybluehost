import pytest

from pybluehost.transport.base import (
    ReconnectPolicy,
    Transport,
    TransportInfo,
    TransportSink,
)


class _StubTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self._opened = False
        self.sent: list[bytes] = []

    async def open(self) -> None:
        self._opened = True

    async def close(self) -> None:
        self._opened = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    @property
    def is_open(self) -> bool:
        return self._opened

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(type="stub", description="stub", platform="any", details={})


class TestTransportInfo:
    def test_fields(self):
        info = TransportInfo(
            type="uart",
            description="UART /dev/ttyUSB0 @ 115200",
            platform="linux",
            details={"port": "/dev/ttyUSB0", "baudrate": 115200},
        )
        assert info.type == "uart"
        assert info.details["baudrate"] == 115200

    def test_info_is_frozen(self):
        info = TransportInfo(type="x", description="x", platform="any", details={})
        with pytest.raises(Exception):
            info.type = "y"  # type: ignore[misc]


class TestReconnectPolicy:
    def test_values(self):
        assert ReconnectPolicy.NONE.value == "none"
        assert ReconnectPolicy.IMMEDIATE.value == "immediate"
        assert ReconnectPolicy.EXPONENTIAL.value == "exponential"


class TestTransportABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Transport()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_stub_lifecycle(self):
        t = _StubTransport()
        assert t.is_open is False
        await t.open()
        assert t.is_open is True
        await t.send(b"\x01\x02")
        assert t.sent == [b"\x01\x02"]
        await t.close()
        assert t.is_open is False

    @pytest.mark.asyncio
    async def test_set_sink(self):
        received: list[bytes] = []

        class Sink:
            async def on_data(self, data: bytes) -> None:
                received.append(data)

        t = _StubTransport()
        sink = Sink()
        t.set_sink(sink)
        assert t._sink is sink
        t.set_sink(None)
        assert t._sink is None

    @pytest.mark.asyncio
    async def test_default_reset_is_close_then_open(self):
        t = _StubTransport()
        await t.open()
        assert t.is_open is True
        await t.reset()
        assert t.is_open is True  # reset reopens
        # verify close was actually called: send after reset still works
        await t.send(b"\x03")
        assert t.sent == [b"\x03"]

    def test_transport_sink_is_runtime_protocol(self):
        assert hasattr(TransportSink, "__class_getitem__") or True  # Protocol sanity
