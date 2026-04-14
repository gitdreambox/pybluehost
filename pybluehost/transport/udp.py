from __future__ import annotations

import asyncio

from pybluehost.transport.base import Transport, TransportInfo


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    def datagram_received(self, data: bytes, addr) -> None:
        self._queue.put_nowait(data)


class UDPTransport(Transport):
    """One complete HCI packet per UDP datagram. No H4 reassembly needed."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._drain_task: asyncio.Task[None] | None = None

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._queue),  # type: ignore[arg-type]
            remote_addr=(self._host, self._port),
        )
        self._drain_task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        assert self._queue is not None
        try:
            while True:
                data = await self._queue.get()
                if self._sink is not None:
                    await self._sink.on_data(data)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._queue = None

    async def send(self, data: bytes) -> None:
        if self._transport is None:
            raise RuntimeError("UDPTransport not open")
        self._transport.sendto(data)

    @property
    def is_open(self) -> bool:
        return self._transport is not None

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="udp",
            description=f"UDP {self._host}:{self._port}",
            platform="any",
            details={"host": self._host, "port": self._port},
        )
