"""Tests for the live ConsoleSink used by --trace=hci."""
from __future__ import annotations

import io

import pytest

from pybluehost.core.trace import Direction, TraceEvent, TraceSystem
from pybluehost.core.trace_console import ConsoleSink
from pybluehost.hci.packets import HCI_Reset


def _make_event(packet, direction=Direction.DOWN, layer="hci"):
    from datetime import datetime, timezone

    return TraceEvent(
        timestamp=0.0,
        wall_clock=datetime.now(timezone.utc),
        source_layer=layer,
        direction=direction,
        raw_bytes=packet.to_bytes() if packet is not None else b"",
        decoded=packet,
        connection_handle=None,
        metadata={},
    )


@pytest.mark.asyncio
async def test_console_sink_writes_compact_line_for_known_command():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    await sink.on_trace(_make_event(HCI_Reset()))
    out = buf.getvalue()
    assert "↓ HCI" in out
    assert "HCI_Reset" in out
    assert "\x1b[" not in out  # no ANSI when color=False


@pytest.mark.asyncio
async def test_console_sink_color_true_emits_ansi_escapes():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=True)
    await sink.on_trace(_make_event(HCI_Reset()))
    out = buf.getvalue()
    assert "\x1b[" in out


@pytest.mark.asyncio
async def test_console_sink_filters_by_layer_set():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, layers={"hci"})
    await sink.on_trace(_make_event(HCI_Reset(), layer="sm"))
    assert buf.getvalue() == ""


@pytest.mark.asyncio
async def test_console_sink_skips_when_decoded_missing():
    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    event = TraceEvent(
        timestamp=0.0,
        wall_clock=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        source_layer="hci",
        direction=Direction.DOWN,
        raw_bytes=b"\xff",
        decoded=None,
        connection_handle=None,
        metadata={},
    )
    await sink.on_trace(event)
    out = buf.getvalue()
    # Falls back to '<undecoded ...>' line, not an error.
    assert "undecoded" in out


def test_default_color_is_off_when_not_a_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    buf = io.StringIO()  # not a TTY
    sink = ConsoleSink(stream=buf)  # color=None -> auto
    assert sink._color is False


def test_no_color_env_var_forces_off(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    sink = ConsoleSink()  # default stream=stderr
    assert sink._color is False


def test_force_color_env_var_forces_on(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    sink = ConsoleSink()
    assert sink._color is True
