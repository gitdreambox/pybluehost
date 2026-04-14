from __future__ import annotations

import asyncio

import serial_asyncio

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.h4 import H4Framer


class UARTTransport(Transport):
    """H4 HCI framing over a serial port (pyserial-asyncio backend)."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        super().__init__()
        self._port = port
        self._baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._framer = H4Framer()

    async def open(self) -> None:
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self._port, baudrate=self._baudrate
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    async def send(self, data: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("UARTTransport not open")
        self._writer.write(data)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    return
                for packet in self._framer.feed(chunk):
                    if self._sink is not None:
                        await self._sink.on_data(packet)
        except asyncio.CancelledError:
            raise

    @property
    def is_open(self) -> bool:
        return self._writer is not None

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="uart",
            description=f"UART {self._port} @ {self._baudrate}",
            platform="any",
            details={"port": self._port, "baudrate": self._baudrate},
        )
