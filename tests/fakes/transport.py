"""FakeTransport — records sent bytes, injects received bytes."""
from __future__ import annotations

from pybluehost.transport.base import Transport, TransportInfo


class FakeTransport(Transport):
    """Records all sent bytes; allows injecting received bytes via inject()."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []
        self._open = False

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def inject(self, data: bytes) -> None:
        """Simulate receiving data from the controller."""
        if self._sink:
            await self._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="fake", description="FakeTransport",
            platform="test", details={},
        )

    def clear(self) -> None:
        """Reset sent list between test cases."""
        self.sent.clear()
