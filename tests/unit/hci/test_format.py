"""Tests for format_hci_packet() — compact and expanded rendering."""
from __future__ import annotations

import pytest

from pybluehost.core.trace import Direction
from pybluehost.hci.format import format_hci_packet
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_LE_Meta_Event,
    HCI_Reset,
    decode_hci_packet,
)


def _down_compact(packet) -> str:
    return format_hci_packet(packet, direction=Direction.DOWN, color=False, expand=False)


def _up_compact(packet) -> str:
    return format_hci_packet(packet, direction=Direction.UP, color=False, expand=False)


def test_compact_known_command_renders_name():
    out = _down_compact(HCI_Reset())
    assert "↓ HCI" in out
    assert "Cmd" in out
    assert "HCI_Reset" in out


def test_compact_command_complete_success_single_line():
    raw = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])  # CC, Reset, status=Success
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert out.count("\n") == 0
    assert "↑ HCI" in out
    assert "Evt" in out
    assert "Command_Complete" in out
    assert "status=Success" in out


def test_compact_unknown_event_uses_event_code_hex():
    raw = bytes([0x04, 0xFE, 0x02, 0x01, 0x02])
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert "0xFE" in out


def test_compact_le_meta_advertising_report_summarizes():
    body = bytes([0x01, 0x00, 0x00]) + bytes([0x06, 0x05, 0x04, 0x03, 0x02, 0x01]) + bytes([0x00, 0xC9])
    raw = bytes([0x04, 0x3E, len(body) + 1, 0x02]) + body
    pkt = decode_hci_packet(raw)
    out = _up_compact(pkt)
    assert "LE_Advertising_Report" in out
    assert "01:02:03:04:05:06" in out
    assert "-55 dBm" in out
