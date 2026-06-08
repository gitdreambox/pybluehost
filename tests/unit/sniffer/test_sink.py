from datetime import datetime, timezone

import pytest

from pybluehost.core.trace import Direction, TraceEvent
from pybluehost.sniffer.backend import SnifferBackend
from pybluehost.sniffer.sink import VirtualSnifferSink


class _FakeBackend(SnifferBackend):
    def __init__(self):
        self.calls = []
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def inject(self, h4_type, direction, payload, wall_clock):
        self.calls.append((h4_type, direction, payload, wall_clock))

    async def stop(self):
        self.stopped = True


def _hci_event(layer: str, direction: Direction, raw: bytes) -> TraceEvent:
    return TraceEvent(
        timestamp=1.0,
        wall_clock=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=raw,
        decoded=None,
        connection_handle=None,
        metadata={},
    )


async def test_sink_strips_h4_and_dispatches():
    backend = _FakeBackend()
    sink = VirtualSnifferSink(backend)
    # HCI_Reset command: H4=0x01 + opcode(0x0C03) + len(0)
    raw = bytes.fromhex("01 03 0C 00")
    await sink.on_trace(_hci_event("hci", Direction.DOWN, raw))
    assert len(backend.calls) == 1
    h4, direction, payload, _wall = backend.calls[0]
    assert h4 == 0x01
    assert direction == Direction.DOWN
    assert payload == bytes.fromhex("03 0C 00")   # H4 byte stripped


async def test_sink_filters_non_hci_layer():
    backend = _FakeBackend()
    sink = VirtualSnifferSink(backend)
    await sink.on_trace(_hci_event("transport", Direction.UP, b"\x01\x02"))
    await sink.on_trace(_hci_event("sm:gap", Direction.UP, b""))
    assert backend.calls == []


async def test_sink_skips_empty_raw():
    backend = _FakeBackend()
    sink = VirtualSnifferSink(backend)
    await sink.on_trace(_hci_event("hci", Direction.UP, b""))
    assert backend.calls == []


async def test_sink_skips_unknown_h4_type_and_warns_once(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="pybluehost.sniffer.sink")
    backend = _FakeBackend()
    sink = VirtualSnifferSink(backend)
    # 0x06 is not a known H4 type
    await sink.on_trace(_hci_event("hci", Direction.DOWN, b"\x06\xAA\xBB"))
    await sink.on_trace(_hci_event("hci", Direction.DOWN, b"\x06\xCC"))  # same type
    assert backend.calls == []
    # warns once for 0x06
    matches = [r for r in caplog.records if "0x06" in r.getMessage()]
    assert len(matches) == 1


async def test_sink_close_stops_backend():
    backend = _FakeBackend()
    sink = VirtualSnifferSink(backend)
    await sink.close()
    assert backend.stopped is True
