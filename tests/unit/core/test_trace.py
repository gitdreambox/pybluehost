# tests/unit/core/test_trace.py
import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import struct

from pybluehost.core.trace import (
    TraceEvent,
    Direction,
    TraceSystem,
    RingBufferSink,
    CallbackSink,
    JsonSink,
    BtsnoopSink,
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


class TestJsonSink:
    @pytest.mark.asyncio
    async def test_writes_jsonl(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01\x03\x0c\x00"))
        await sink.flush()
        await sink.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["layer"] == "hci"
        assert obj["dir"] == "down"
        assert obj["hex"] == "01030c00"
        assert "ts" in obj
        assert "wall" in obj

    @pytest.mark.asyncio
    async def test_multiple_events(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("l2cap", Direction.UP, b"\x02"))
        await sink.flush()
        await sink.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        obj0 = json.loads(lines[0])
        obj1 = json.loads(lines[1])
        assert obj1["layer"] != obj0["layer"]
        assert obj1["layer"] == "l2cap"

    @pytest.mark.asyncio
    async def test_decoded_included(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        event = TraceEvent(
            timestamp=0.0,
            wall_clock=datetime.now(timezone.utc),
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01",
            decoded={"opcode": "HCI_Reset"},
            connection_handle=0x40,
            metadata={"extra": "info"},
        )
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        obj = json.loads(path.read_text().strip())
        assert obj["decoded"] == {"opcode": "HCI_Reset"}
        assert obj["handle"] == 0x40
        assert obj["meta"] == {"extra": "info"}

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.close()
        await sink.close()  # must not raise

    @pytest.mark.asyncio
    async def test_flush_after_close_is_safe(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await sink.close()
        await sink.flush()  # must not raise

    @pytest.mark.asyncio
    async def test_decode_false_omits_decoded(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        sink = JsonSink(str(path), decode=False)
        event = TraceEvent(
            timestamp=0.0,
            wall_clock=datetime.now(timezone.utc),
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01",
            decoded={"key": "value"},
            connection_handle=None,
            metadata={},
        )
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        obj = json.loads(path.read_text().strip())
        assert "decoded" not in obj


class TestBtsnoopSink:
    @pytest.mark.asyncio
    async def test_writes_valid_header(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.close()

        data = path.read_bytes()
        assert data[:8] == b"btsnoop\x00"
        version = struct.unpack(">I", data[8:12])[0]
        assert version == 1
        datalink = struct.unpack(">I", data[12:16])[0]
        assert datalink == 1002  # H4

    @pytest.mark.asyncio
    async def test_writes_packet_record(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))

        event = _make_event("hci", Direction.DOWN, b"\x01\x03\x0c\x00")
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        assert len(data) > 16  # header + at least one record

        offset = 16
        orig_len = struct.unpack(">I", data[offset : offset + 4])[0]
        incl_len = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        flags = struct.unpack(">I", data[offset + 8 : offset + 12])[0]
        assert orig_len == incl_len
        assert orig_len == 4
        assert flags == 0  # sent (DOWN)

    @pytest.mark.asyncio
    async def test_direction_flags(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.on_trace(_make_event("hci", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("hci", Direction.UP, b"\x02"))
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        flags1 = struct.unpack(">I", data[24:28])[0]
        assert flags1 == 0  # sent

        # Second record: offset = 16 (header) + 24 (record header) + 1 (payload)
        rec2_offset = 16 + 24 + 1
        flags2 = struct.unpack(">I", data[rec2_offset + 8 : rec2_offset + 12])[0]
        assert flags2 == 1  # received

    @pytest.mark.asyncio
    async def test_timestamp_encoding(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        fixed_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = TraceEvent(
            timestamp=0.0,
            wall_clock=fixed_dt,
            source_layer="hci",
            direction=Direction.DOWN,
            raw_bytes=b"\x01",
            decoded=None,
            connection_handle=None,
            metadata={},
        )
        await sink.on_trace(event)
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        ts_bytes = data[32:40]  # after 16-byte header + 16-byte record prefix
        ts_val = struct.unpack(">q", ts_bytes)[0]
        expected = int(fixed_dt.timestamp() * 1_000_000) + 946684800_000_000
        assert ts_val == expected

    @pytest.mark.asyncio
    async def test_ignores_non_hci_events(self, tmp_path: Path):
        path = tmp_path / "trace.cfa"
        sink = BtsnoopSink(str(path))
        await sink.on_trace(_make_event("l2cap", Direction.DOWN, b"\x01"))
        await sink.on_trace(_make_event("sm:conn", Direction.UP, b"\x01"))
        await sink.flush()
        await sink.close()

        data = path.read_bytes()
        assert len(data) == 16  # header only, no records


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
