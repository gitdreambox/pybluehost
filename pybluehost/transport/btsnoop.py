from __future__ import annotations

import asyncio
import struct
from pathlib import Path

from pybluehost.transport.base import Transport, TransportInfo


class BtsnoopTransport(Transport):
    """Replay an existing btsnoop capture file, delivering records to the sink.

    Writes are silently dropped (replay is read-only).
    """

    def __init__(self, path: str | Path, *, realtime: bool = False) -> None:
        super().__init__()
        self._path = Path(path)
        self._realtime = realtime
        self._replay_task: asyncio.Task[None] | None = None
        self._open = False

    async def open(self) -> None:
        self._open = True
        self._replay_task = asyncio.create_task(self._replay())

    async def _replay(self) -> None:
        with open(self._path, "rb") as f:
            header = f.read(16)
            if header[:8] != b"btsnoop\x00":
                raise ValueError(f"not a btsnoop file: {self._path}")
            last_ts_us: int | None = None
            while True:
                rec_header = f.read(24)
                if len(rec_header) < 24:
                    return
                orig_len, incl_len, flags, drops, ts = struct.unpack(">IIIIq", rec_header)
                payload = f.read(incl_len)
                if len(payload) < incl_len:
                    return
                if self._realtime and last_ts_us is not None:
                    delta = (ts - last_ts_us) / 1_000_000
                    if delta > 0:
                        await asyncio.sleep(delta)
                last_ts_us = ts
                if self._sink is not None and self._open:
                    await self._sink.on_data(payload)

    async def close(self) -> None:
        self._open = False
        if self._replay_task is not None:
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass
            self._replay_task = None

    async def send(self, data: bytes) -> None:
        return  # silently drop — replay is read-only

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="btsnoop",
            description=f"btsnoop replay {self._path}",
            platform="any",
            details={"path": str(self._path), "realtime": self._realtime},
        )
