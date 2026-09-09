"""ClassicDiscovery RSSI/EIR inquiry format support.

Controllers power up in inquiry mode 0 (legacy) and only emit the legacy
Inquiry_Result event (no RSSI, no name).  ClassicDiscovery.start() must set
Write_Inquiry_Mode(2) (EIR with RSSI) before HCI_Inquiry, and handle both
0x22 (Inquiry_Result_with_RSSI) and 0x2F (Extended_Inquiry_Result) events.
"""
from __future__ import annotations

import pytest

from pybluehost.classic.gap import ClassicDiscovery, InquiryConfig
from pybluehost.core.gap_common import DeviceInfo
from pybluehost.hci.constants import ErrorCode, HCI_INQUIRY
from pybluehost.hci.packets import HCI_Command_Complete_Event, HCIEvent

# OGF 3 (Controller & Baseband) / OCF 0x0045 → 0x0C45
HCI_WRITE_INQUIRY_MODE = 0x0C45

_EVENT_INQUIRY_RESULT_WITH_RSSI = 0x22
_EVENT_EXTENDED_INQUIRY_RESULT = 0x2F


class FakeHCI:
    def __init__(self, fail_modes: set[int] | None = None) -> None:
        self.commands: list = []
        self.fail_modes = fail_modes or set()

    async def send_command(self, cmd: object) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        if cmd.opcode in self.fail_modes:
            raise RuntimeError("command disallowed")
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )


def _rssi_record(addr_le: bytes, cod: int, rssi: int) -> bytes:
    """A 15-byte Inquiry_Result_with_RSSI record."""
    return (
        addr_le
        + bytes([0x01])      # page_scan_rep_mode
        + bytes([0x00])      # page_scan_period_mode
        + bytes([0x00])      # page_scan_mode
        + cod.to_bytes(3, "little")
        + bytes(2)           # clock_offset
        + bytes([rssi & 0xFF])
    )


async def test_start_sends_write_inquiry_mode_before_inquiry():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    await disc.start()
    mode_cmds = [c for c in hci.commands if c.opcode == HCI_WRITE_INQUIRY_MODE]
    inq_cmds = [c for c in hci.commands if c.opcode == HCI_INQUIRY]
    assert len(mode_cmds) == 1
    assert mode_cmds[0].parameters == b"\x02"  # mode 2 = EIR with RSSI
    assert hci.commands.index(mode_cmds[0]) < hci.commands.index(inq_cmds[0])


async def test_start_tolerates_write_inquiry_mode_failure():
    hci = FakeHCI(fail_modes={HCI_WRITE_INQUIRY_MODE})
    disc = ClassicDiscovery(hci=hci)
    await disc.start()  # must not raise; falls back to legacy inquiry results
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_INQUIRY in opcodes


async def test_parses_inquiry_result_with_rssi_event():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    results: list[DeviceInfo] = []
    disc.on_result(results.append)
    # rssi byte 0xB0 = 176 ≥ 128 → -80
    params = (
        b"\x02"
        + _rssi_record(bytes.fromhex("6bf51b8d8d1a"), 0x0C0204, -60)
        + _rssi_record(bytes.fromhex("665544332211"), 0x5B020C, 176)
    )
    await disc.on_hci_event(
        HCIEvent(event_code=_EVENT_INQUIRY_RESULT_WITH_RSSI, parameters=params)
    )
    assert len(results) == 2
    assert str(results[0].address) == "1A:8D:8D:1B:F5:6B"
    assert results[0].class_of_device == 0x0C0204
    assert results[0].rssi == -60
    assert str(results[1].address) == "11:22:33:44:55:66"
    assert results[1].rssi == -80


async def test_parses_extended_inquiry_result_event():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    results: list[DeviceInfo] = []
    disc.on_result(results.append)
    eir = b"\x0C\x09TestClassic" + bytes(240 - 13)  # Complete Local Name (len=12, type=0x09)
    params = (
        b"\x01"                                   # num_responses = 1
        + bytes.fromhex("6bf51b8d8d1a")           # BD_ADDR LE
        + bytes([0x01])                           # page_scan_rep_mode
        + bytes([0x00])                           # reserved
        + (0x0C0204).to_bytes(3, "little")        # CoD
        + bytes(2)                                # clock_offset
        + bytes([-42 & 0xFF])                     # rssi
        + eir
    )
    await disc.on_hci_event(
        HCIEvent(event_code=_EVENT_EXTENDED_INQUIRY_RESULT, parameters=params)
    )
    assert len(results) == 1
    assert str(results[0].address) == "1A:8D:8D:1B:F5:6B"
    assert results[0].class_of_device == 0x0C0204
    assert results[0].rssi == -42
    assert results[0].name == "TestClassic"


async def test_legacy_inquiry_result_has_no_rssi():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    results: list[DeviceInfo] = []
    disc.on_result(results.append)
    params = (
        b"\x01"
        + bytes.fromhex("6bf51b8d8d1a")
        + b"\x01\x00"
        + (0x0C0204).to_bytes(3, "little")
        + bytes(2)
    )
    from pybluehost.hci.constants import EventCode

    await disc.on_hci_event(
        HCIEvent(event_code=EventCode.INQUIRY_RESULT, parameters=params)
    )
    assert len(results) == 1
    assert results[0].rssi is None
    assert results[0].name is None
