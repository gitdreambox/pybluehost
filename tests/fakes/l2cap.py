"""FakeChannelEvents — captures channel events for assertion in tests."""
from __future__ import annotations


class FakeChannelEvents:
    """Captures channel events for assertion in tests."""

    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.closed: bool = False
        self.mtu_changed_to: int | None = None

    async def on_data(self, data: bytes) -> None:
        self.received.append(data)

    async def on_close(self) -> None:
        self.closed = True

    async def on_mtu_changed(self, mtu: int) -> None:
        self.mtu_changed_to = mtu

    def clear(self) -> None:
        self.received.clear()
        self.closed = False
        self.mtu_changed_to = None
