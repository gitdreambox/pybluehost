"""Verify HCIController._emit_trace attaches the decoded packet to TraceEvent."""
from __future__ import annotations

import pytest

from pybluehost.core.trace import Direction, TraceEvent, TraceSystem
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCI_Reset, HCICommand


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def on_trace(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None: ...
    async def close(self) -> None: ...


@pytest.mark.asyncio
async def test_emit_trace_decodes_and_attaches_packet():
    trace = TraceSystem()
    sink = _RecordingSink()
    trace.add_sink(sink)
    await trace.start()

    raw = HCI_Reset().to_bytes()
    controller = HCIController(transport=None, trace=trace)
    controller._emit_trace(Direction.DOWN, raw)

    await trace.stop()

    assert len(sink.events) == 1
    decoded = sink.events[0].decoded
    assert isinstance(decoded, HCICommand)


@pytest.mark.asyncio
async def test_emit_trace_falls_back_to_none_on_decode_error():
    trace = TraceSystem()
    sink = _RecordingSink()
    trace.add_sink(sink)
    await trace.start()

    controller = HCIController(transport=None, trace=trace)
    controller._emit_trace(Direction.DOWN, b"\xff")  # invalid

    await trace.stop()

    assert sink.events[0].decoded is None
