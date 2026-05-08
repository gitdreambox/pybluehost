"""Regression: Stack.trace dispatch loop must run BEFORE sinks attach.

Prior to this fix, Stack._build only started the TraceSystem dispatch loop
when cfg.trace_sinks was non-empty at build time. Sinks attached later (e.g.
ConsoleSink via attach_console_sink in cli/_lifecycle) had their events
queued instead of dispatched until stack.close() drained the queue, which
made --trace=hci appear to print everything at Ctrl+C instead of live.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from pybluehost.core.trace import Direction, TraceEvent
from pybluehost.stack import Stack


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def on_trace(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None: ...
    async def close(self) -> None: ...


@pytest.mark.asyncio
async def test_sink_attached_after_build_receives_events_live():
    stack = await Stack.virtual()
    try:
        sink = _RecordingSink()
        stack.trace.add_sink(sink)

        # Emit one synthetic event after sink attach.
        stack.trace.emit(TraceEvent(
            timestamp=0.0,
            wall_clock=datetime.now(timezone.utc),
            source_layer="test",
            direction=Direction.DOWN,
            raw_bytes=b"",
            decoded=None,
            connection_handle=None,
            metadata={},
        ))

        # Give the dispatch loop one tick to deliver. If it is not running,
        # the event will sit in the queue until stack.close() drains it,
        # and this assertion will fail.
        for _ in range(10):
            await asyncio.sleep(0.01)
            if any(e.source_layer == "test" for e in sink.events):
                break

        assert any(e.source_layer == "test" for e in sink.events), (
            "TraceSystem dispatch loop didn't deliver post-attach event live"
        )
    finally:
        await stack.close()
