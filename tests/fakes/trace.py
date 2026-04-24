"""NullTrace — no-op trace for tests that don't need tracing."""
from __future__ import annotations

from pybluehost.core.trace import TraceEvent, TraceSink


class NullTrace:
    """No-op trace matching TraceSystem interface — discards all events."""

    def __init__(self) -> None:
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def add_sink(self, sink: TraceSink) -> None:
        pass

    def remove_sink(self, sink: TraceSink) -> None:
        pass

    def emit(self, event: TraceEvent) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
