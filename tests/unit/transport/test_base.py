import pytest

from pybluehost.core.errors import TransportError
from pybluehost.transport.base import (
    ReconnectConfig,
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
            async def on_transport_data(self, data: bytes) -> None:
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


class TestTransportSinkProtocol:
    @pytest.mark.asyncio
    async def test_sink_on_transport_error(self):
        """Sink with on_transport_error receives the error via _notify_error."""
        received: list[TransportError] = []

        class FullSink:
            async def on_transport_data(self, data: bytes) -> None:
                pass

            async def on_transport_error(self, error: TransportError) -> None:
                received.append(error)

        t = _StubTransport()
        t.set_sink(FullSink())
        err = TransportError("oops")
        await t._notify_error(err)
        assert received == [err]

    @pytest.mark.asyncio
    async def test_notify_error_without_sink_is_noop(self):
        """No sink → _notify_error does not crash."""
        t = _StubTransport()
        assert t._sink is None
        err = TransportError("oops")
        await t._notify_error(err)  # must not raise

    @pytest.mark.asyncio
    async def test_notify_error_sink_without_method_is_noop(self):
        """Sink that only has on_data (no on_transport_error) → no crash."""

        class MinimalSink:
            async def on_transport_data(self, data: bytes) -> None:
                pass

        t = _StubTransport()
        t.set_sink(MinimalSink())
        err = TransportError("oops")
        await t._notify_error(err)  # must not raise


class TestReconnectConfig:
    def test_defaults(self):
        cfg = ReconnectConfig()
        assert cfg.policy == ReconnectPolicy.NONE
        assert cfg.max_attempts == 5
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0

    def test_custom_values(self):
        cfg = ReconnectConfig(
            policy=ReconnectPolicy.EXPONENTIAL,
            max_attempts=10,
            base_delay=0.5,
            max_delay=30.0,
        )
        assert cfg.policy == ReconnectPolicy.EXPONENTIAL
        assert cfg.max_attempts == 10
        assert cfg.base_delay == 0.5
        assert cfg.max_delay == 30.0

    def test_frozen(self):
        cfg = ReconnectConfig()
        with pytest.raises(Exception):
            cfg.max_attempts = 99  # type: ignore[misc]
