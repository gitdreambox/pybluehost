from __future__ import annotations

import asyncio
import json as _json
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol


class Direction(Enum):
    UP = "host \u2190 controller"
    DOWN = "host \u2192 controller"


@dataclass(frozen=True)
class TraceEvent:
    timestamp: float
    wall_clock: datetime
    source_layer: str
    direction: Direction
    raw_bytes: bytes
    decoded: dict[str, Any] | None
    connection_handle: int | None
    metadata: dict[str, Any]


class TraceSink(Protocol):
    async def on_trace(self, event: TraceEvent) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


class TraceSystem:
    def __init__(self) -> None:
        self._sinks: list[TraceSink] = []
        self._queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def add_sink(self, sink: TraceSink) -> None:
        self._sinks.append(sink)

    def remove_sink(self, sink: TraceSink) -> None:
        self._sinks.remove(sink)

    def emit(self, event: TraceEvent) -> None:
        if not self._enabled:
            return
        self._queue.put_nowait(event)

    async def start(self) -> None:
        self._task = asyncio.ensure_future(self._dispatch_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        while not self._queue.empty():
            event = self._queue.get_nowait()
            for sink in self._sinks:
                await sink.on_trace(event)

        for sink in self._sinks:
            await sink.flush()
            await sink.close()

    async def _dispatch_loop(self) -> None:
        try:
            while True:
                event = await self._queue.get()
                for sink in self._sinks:
                    await sink.on_trace(event)
        except asyncio.CancelledError:
            return


class RingBufferSink:
    def __init__(self, capacity: int = 1000) -> None:
        self._buffer: deque[TraceEvent] = deque(maxlen=capacity)

    async def on_trace(self, event: TraceEvent) -> None:
        self._buffer.append(event)

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def recent(self, n: int = 20) -> list[TraceEvent]:
        items = list(self._buffer)
        return items[-n:]

    def filter(
        self,
        layer: str | None = None,
        direction: Direction | None = None,
    ) -> list[TraceEvent]:
        result = list(self._buffer)
        if layer is not None:
            result = [e for e in result if e.source_layer == layer]
        if direction is not None:
            result = [e for e in result if e.direction == direction]
        return result

    def dump(self) -> str:
        lines = []
        for e in self._buffer:
            hex_str = e.raw_bytes.hex() if e.raw_bytes else "(empty)"
            lines.append(f"[{e.source_layer}] {e.direction.name} {hex_str}")
        return "\n".join(lines)


class CallbackSink:
    def __init__(self, callback: Callable[[TraceEvent], Awaitable[None]]) -> None:
        self._callback = callback

    async def on_trace(self, event: TraceEvent) -> None:
        await self._callback(event)

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass


class JsonSink:
    """JSON Lines trace sink — one JSON object per line."""

    def __init__(self, path: str | Path, decode: bool = True) -> None:
        self._path = Path(path)
        self._decode = decode
        self._file = open(self._path, "w", encoding="utf-8")

    async def on_trace(self, event: TraceEvent) -> None:
        obj: dict[str, Any] = {
            "ts": event.timestamp,
            "wall": event.wall_clock.isoformat(),
            "layer": event.source_layer,
            "dir": event.direction.name.lower(),
            "hex": event.raw_bytes.hex(),
        }
        if self._decode and event.decoded is not None:
            obj["decoded"] = event.decoded
        if event.connection_handle is not None:
            obj["handle"] = event.connection_handle
        if event.metadata:
            obj["meta"] = event.metadata
        self._file.write(_json.dumps(obj) + "\n")

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.close()
