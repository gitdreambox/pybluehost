from __future__ import annotations

from pybluehost.transport.base import Transport, TransportInfo


class LoopbackTransport(Transport):
    """In-memory loopback. Bytes sent on one instance are delivered to its peer's sink."""

    def __init__(self) -> None:
        super().__init__()
        self._peer: "LoopbackTransport | None" = None
        self._open = False

    @classmethod
    def pair(cls) -> tuple["LoopbackTransport", "LoopbackTransport"]:
        a = cls()
        b = cls()
        a._peer = b
        b._peer = a
        return a, b

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("LoopbackTransport not open")
        if self._peer is None:
            raise RuntimeError("LoopbackTransport has no peer")
        if self._peer._open and self._peer._sink is not None:
            await self._peer._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="loopback",
            description="In-memory loopback transport",
            platform="any",
            details={},
        )
