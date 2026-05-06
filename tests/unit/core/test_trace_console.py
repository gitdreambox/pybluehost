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


@pytest.mark.asyncio
async def test_number_of_completed_packets_suppressed_by_default():
    from pybluehost.hci.packets import HCI_Number_Of_Completed_Packets_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    event = HCI_Number_Of_Completed_Packets_Event(completed={0x40: 1})
    await sink.on_trace(_make_event(event, direction=Direction.UP))
    assert buf.getvalue() == ""


@pytest.mark.asyncio
async def test_number_of_completed_packets_shown_when_explicit_include():
    from pybluehost.hci.packets import HCI_Number_Of_Completed_Packets_Event

    buf = io.StringIO()
    sink = ConsoleSink(
        stream=buf, color=False, include={"Number_Of_Completed_Packets"},
    )
    event = HCI_Number_Of_Completed_Packets_Event(completed={0x40: 1})
    await sink.on_trace(_make_event(event, direction=Direction.UP))
    assert "Number_Of_Completed_Packets" in buf.getvalue()


@pytest.mark.asyncio
async def test_acl_data_truncates_payload_at_default_24_bytes():
    from pybluehost.hci.packets import HCIACLData

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False)
    payload = bytes(range(64))  # 64-byte payload
    pkt = HCIACLData(handle=0x40, pb_flag=0, bc_flag=0, data=payload)
    await sink.on_trace(_make_event(pkt))
    out = buf.getvalue()
    assert "handle=0x0040" in out
    assert "len=64" in out
    # First 24 bytes appear; later bytes do not.
    truncated = payload[:24]
    later = payload[40:]
    assert (truncated.hex() in out.lower()) or (truncated.hex(' ') in out)
    assert later.hex() not in out.lower()


@pytest.mark.asyncio
async def test_acl_data_full_payload_when_full_acl_enabled():
    from pybluehost.hci.packets import HCIACLData

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, full_acl=True)
    payload = bytes(range(40))
    pkt = HCIACLData(handle=0x40, pb_flag=0, bc_flag=0, data=payload)
    await sink.on_trace(_make_event(pkt))
    out = buf.getvalue()
    assert (payload[24:].hex(" ") in out) or (payload[24:].hex() in out)


@pytest.mark.asyncio
async def test_repeated_le_advertising_reports_collapse_for_same_address():
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, adv_collapse_window=5.0)

    body = bytes([0x01, 0x00, 0x00]) + bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01]) + bytes([0x00, 0xC9])
    event = HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body)

    # 5 reports for the same address.
    for _ in range(5):
        await sink.on_trace(_make_event(event, direction=Direction.UP))

    out = buf.getvalue()
    # First one printed; the next four collapsed (no printing yet).
    assert out.count("LE_Advertising_Report") == 1


@pytest.mark.asyncio
async def test_collapse_summary_emitted_when_new_address_arrives():
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    buf = io.StringIO()
    sink = ConsoleSink(stream=buf, color=False, adv_collapse_window=5.0)

    addr_a = bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01])
    addr_b = bytes([0x66, 0x55, 0x44, 0x33, 0x22, 0x11])

    body_a = bytes([0x01, 0x00, 0x00]) + addr_a + bytes([0x00, 0xC9])
    body_b = bytes([0x01, 0x00, 0x00]) + addr_b + bytes([0x00, 0xC0])

    for _ in range(3):
        await sink.on_trace(_make_event(
            HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body_a),
            direction=Direction.UP,
        ))
    # Now an address-B report arrives — emits the collapsed-A summary first.
    await sink.on_trace(_make_event(
        HCI_LE_Meta_Event(subevent_code=0x02, subevent_parameters=body_b),
        direction=Direction.UP,
    ))

    out = buf.getvalue()
    # 2 additional A reports collapsed (3 total - 1 already shown when first appeared).
    assert "× 2" in out or "x 2" in out
    assert "01:02:03:04:05:06" in out
    assert "11:22:33:44:55:66" in out
