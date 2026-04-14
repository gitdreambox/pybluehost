# tests/unit/core/test_trace.py
import asyncio
from datetime import datetime, timezone

import pytest

from pybluehost.core.trace import (
    TraceEvent,
    Direction,
    TraceSystem,
    RingBufferSink,
    CallbackSink,
)


class TestTraceEvent:
    def test_create(self):
        event = TraceEvent(
            timestamp=1000.0,
            wall_clock=datetime(2026, 4, 14, tzinfo=timezone.utc),
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01\x03\x0c\x00",
            decoded={"opcode": "HCI_Reset"},
            connection_handle=None,
            metadata={},
        )
        assert event.source_layer == "hci"
        assert event.direction == Direction.DOWN
        assert event.raw_bytes == b"\x01\x03\x0c\x00"

    def test_frozen(self):
        event = TraceEvent(
            timestamp=0, wall_clock=datetime.now(timezone.utc),
            source_layer="hci", direction=Direction.UP,
            raw_bytes=b"", decoded=None,
            connection_handle=None, metadata={},
        )
        with pytest.raises(AttributeError):
            event.source_layer = "l2cap"  # type: ignore[misc]


class TestDirection:
    def test_values(self):
        assert Direction.UP.value == "host \u2190 controller"
        assert Direction.DOWN.value == "host \u2192 controller"


class TestTraceSystem:
    @pytest.mark.asyncio
    async def test_emit_to_single_sink(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        ts = TraceSystem()
        ts.add_sink(CallbackSink(handler))
        await ts.start()

        event = _make_event("hci", Direction.DOWN, b"\x01")
        ts.emit(event)
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 1
        assert received[0].raw_bytes == b"\x01"

    @pytest.mark.asyncio
    async def test_emit_to_multiple_sinks(self):
        count_a = 0
        count_b = 0

        async def sink_a(event: TraceEvent) -> None:
            nonlocal count_a
            count_a += 1

        async def sink_b(event: TraceEvent) -> None:
            nonlocal count_b
            count_b += 1

        ts = TraceSystem()
        ts.add_sink(CallbackSink(sink_a))
        ts.add_sink(CallbackSink(sink_b))
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert count_a == 1
        assert count_b == 1

    @pytest.mark.asyncio
    async def test_disabled_does_not_emit(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        ts = TraceSystem()
        ts.add_sink(CallbackSink(handler))
        ts.enabled = False
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_remove_sink(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        sink = CallbackSink(handler)
        ts = TraceSystem()
        ts.add_sink(sink)
        ts.remove_sink(sink)
        await ts.start()

        ts.emit(_make_event("hci", Direction.DOWN, b"\x01"))
        await asyncio.sleep(0.05)

        await ts.stop()
        assert len(received) == 0


class TestRingBufferSink:
    @pytest.mark.asyncio
    async def test_recent(self):
        ring = RingBufferSink(capacity=5)
        for i in range(3):
            await ring.on_trace(_make_event("hci", Direction.DOWN, bytes([i])))
        assert len(ring.recent(10)) == 3
        assert ring.recent(2) == ring.recent(10)[-2:]

    @pytest.mark.asyncio
    async def test_capacity_overflow(self):
        ring = RingBufferSink(capacity=3)
        for i in range(5):
            await ring.on_trace(_make_event("hci", Direction.DOWN, bytes([i])))
        events = ring.recent(10)
        assert len(events) == 3
        assert events[0].raw_bytes == bytes([2])  # oldest kept

    @pytest.mark.asyncio
    async def test_filter_by_layer(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await ring.on_trace(_make_event("l2cap", Direction.UP, b"\x02"))
        await ring.on_trace(_make_event("hci", Direction.UP, b"\x03"))
        filtered = ring.filter(layer="hci")
        assert len(filtered) == 2

    @pytest.mark.asyncio
    async def test_filter_by_direction(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await ring.on_trace(_make_event("hci", Direction.UP, b"\x02"))
        filtered = ring.filter(direction=Direction.UP)
        assert len(filtered) == 1

    @pytest.mark.asyncio
    async def test_dump_returns_string(self):
        ring = RingBufferSink(capacity=10)
        await ring.on_trace(_make_event("hci", Direction.DOWN, b"\x01\x02"))
        text = ring.dump()
        assert isinstance(text, str)
        assert "hci" in text


class TestCallbackSink:
    @pytest.mark.asyncio
    async def test_callback_called(self):
        received: list[TraceEvent] = []

        async def handler(event: TraceEvent) -> None:
            received.append(event)

        sink = CallbackSink(handler)
        event = _make_event("att", Direction.DOWN, b"\x01")
        await sink.on_trace(event)
        assert len(received) == 1


def _make_event(layer: str, direction: Direction, raw: bytes) -> TraceEvent:
    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime.now(timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=raw,
        decoded=None,
        connection_handle=None,
        metadata={},
    )
