"""inquiry_scan_all + fetch_remote_name。"""
import asyncio

from pybluehost.cli.app.mitm.bredr_recon import (
    fetch_remote_name,
    inquiry_scan_all,
    parse_inquiry_result_entries,
    parse_extended_inquiry_result_entry,
    parse_inquiry_result_with_rssi_entries,
)
from pybluehost.hci.constants import (
    HCI_INQUIRY,
    HCI_REMOTE_NAME_REQUEST,
    EventCode,
)
from pybluehost.hci.packets import HCICommand, HCIEvent

# OGF 3 (Controller & Baseband) / OCF 0x0045 → 0x0C45
HCI_WRITE_INQUIRY_MODE = 0x0C45


def _rssi_entry(addr_hex: str, cod: int, rssi: int) -> bytes:
    """One 15-byte Inquiry_Result_with_RSSI record."""
    return (
        bytes.fromhex(addr_hex)
        + bytes([0x01])          # page_scan_rep_mode
        + bytes([0x00])          # page_scan_period_mode
        + bytes([0x00])          # page_scan_mode
        + cod.to_bytes(3, "little")
        + bytes(2)               # clock_offset
        + bytes([rssi & 0xFF])
    )


def test_parse_inquiry_result_with_rssi_entries_layout():
    raw = bytes([0x02]) + _rssi_entry("F752CD18D538", 0x240404, -60) \
        + _rssi_entry("112233445566", 0x5B020C, -90)
    entries = parse_inquiry_result_with_rssi_entries(raw)
    assert entries == [
        ("38:D5:18:CD:52:F7", 0x240404, -60),
        ("66:55:44:33:22:11", 0x5B020C, -90),
    ]


def test_parse_inquiry_result_with_rssi_entries_negative_rssi():
    # rssi byte 0xB0 = 176 ≥ 128 → -80
    raw = bytes([0x01]) + _rssi_entry("F752CD18D538", 0x240404, 176)
    entries = parse_inquiry_result_with_rssi_entries(raw)
    assert entries == [("38:D5:18:CD:52:F7", 0x240404, -80)]


def test_parse_inquiry_result_with_rssi_entries_truncated():
    # num_responses=2 but the second record arrives only half → return just the first one, no exception
    raw = bytes([0x02]) + _rssi_entry("F752CD18D538", 0x240404, -60) \
        + _rssi_entry("112233445566", 0x5B020C, -90)[:7]
    entries = parse_inquiry_result_with_rssi_entries(raw)
    assert entries == [("38:D5:18:CD:52:F7", 0x240404, -60)]


def test_parse_inquiry_result_with_rssi_entries_empty():
    assert parse_inquiry_result_with_rssi_entries(b"") == []


def test_parse_inquiry_result_entries_layout():
    raw = (
        bytes([0x01])
        + bytes.fromhex("F7 52 CD 18 D5 38".replace(" ", ""))
        + bytes([0x01]) + bytes(2)
        + (0x240404).to_bytes(3, "little")
        + bytes(2)
    )
    entries = parse_inquiry_result_entries(raw)
    assert entries == [("38:D5:18:CD:52:F7", 0x240404)]


def test_parse_extended_inquiry_result_entry_layout():
    raw = (
        bytes([0x01])
        + bytes.fromhex("F752CD18D538")
        + bytes([0x01]) + bytes([0x00])
        + (0x240404).to_bytes(3, "little")
        + bytes(2)          # clock
        + bytes([-60 & 0xFF])  # rssi
        + b"\x09\x05Dev-BR" + bytes(240 - 8)   # EIR 240B
    )
    addr, cod, eir, rssi = parse_extended_inquiry_result_entry(raw)
    assert addr == "38:D5:18:CD:52:F7"
    assert cod == 0x240404
    assert rssi == -60
    assert eir[:8] == b"\x09\x05Dev-BR"


class FakeInqController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list[HCICommand] = []
        self.reply_name = "JBL Live Beam 4"

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event

    async def send_command(self, command):
        self.commands.append(command)
        if command.opcode == HCI_REMOTE_NAME_REQUEST:  # 0x0419
            params = bytes([0x00]) + command.parameters[0:6]
            name = self.reply_name.encode()[:248]
            name = name + bytes(248 - len(name))
            self._on_hci_event(
                HCIEvent.from_bytes(EventCode.REMOTE_NAME_REQUEST_COMPLETE,
                                    params + name)
            )

    def feed_inquiry_result(self):
        raw = (
            bytes([0x01]) + bytes.fromhex("F752CD18D538")
            + bytes([0x01]) + bytes(2)
            + (0x240404).to_bytes(3, "little") + bytes(2)
        )
        self._on_hci_event(HCIEvent.from_bytes(EventCode.INQUIRY_RESULT, raw))


async def test_inquiry_scan_all_collects_devices():
    ctl = FakeInqController()
    task = asyncio.ensure_future(
        inquiry_scan_all(ctl, rounds=2, round_seconds=0.1)
    )
    await asyncio.sleep(0.03)
    ctl.feed_inquiry_result()
    entries = await asyncio.wait_for(task, 3.0)
    assert len(entries) == 1
    assert entries[0].identity.address == "38:D5:18:CD:52:F7"
    assert entries[0].identity.class_of_device == 0x240404
    assert entries[0].rssi is None  # standard inquiry result has no RSSI


async def test_inquiry_scan_all_sets_eir_inquiry_mode():
    ctl = FakeInqController()
    await asyncio.wait_for(
        inquiry_scan_all(ctl, rounds=1, round_seconds=0.01), 3.0
    )
    opcodes = [c.opcode for c in ctl.commands]
    assert HCI_WRITE_INQUIRY_MODE in opcodes
    assert HCI_INQUIRY in opcodes
    # Write_Inquiry_Mode must be sent before HCI_INQUIRY
    mode_cmd = next(
        c for c in ctl.commands if c.opcode == HCI_WRITE_INQUIRY_MODE
    )
    inq_cmd = next(c for c in ctl.commands if c.opcode == HCI_INQUIRY)
    assert ctl.commands.index(mode_cmd) < ctl.commands.index(inq_cmd)
    assert mode_cmd.parameters == b"\x02"  # mode 2 = EIR with RSSI


async def test_inquiry_scan_all_tolerates_write_inquiry_mode_failure():
    class FailingCtl(FakeInqController):
        async def send_command(self, command):
            if command.opcode == HCI_WRITE_INQUIRY_MODE:
                raise RuntimeError("command disallowed")
            await super().send_command(command)

    ctl = FailingCtl()
    entries = await asyncio.wait_for(
        inquiry_scan_all(ctl, rounds=1, round_seconds=0.01), 3.0
    )
    assert entries == []  # falls back to legacy inquiry, no crash


async def test_inquiry_scan_all_collects_rssi_events():
    ctl = FakeInqController()

    def feed_rssi_result():
        raw = bytes([0x01]) + _rssi_entry("F752CD18D538", 0x240404, 176)
        ctl._on_hci_event(HCIEvent.from_bytes(0x22, raw))

    task = asyncio.ensure_future(
        inquiry_scan_all(ctl, rounds=2, round_seconds=0.1)
    )
    await asyncio.sleep(0.03)
    feed_rssi_result()
    entries = await asyncio.wait_for(task, 3.0)
    assert len(entries) == 1
    assert entries[0].identity.address == "38:D5:18:CD:52:F7"
    assert entries[0].identity.class_of_device == 0x240404
    assert entries[0].rssi == -80


async def test_fetch_remote_name_roundtrip():
    ctl = FakeInqController()
    name = await asyncio.wait_for(
        fetch_remote_name(ctl, "38:D5:18:CD:52:F7", timeout=2.0), 3.0
    )
    assert name == "JBL Live Beam 4"
    # Inquiry_Cancel (stop inquiry first) and Remote_Name_Request were sent
    from pybluehost.hci.constants import HCI_INQUIRY_CANCEL, HCI_REMOTE_NAME_REQUEST
    opcodes = [c.opcode for c in ctl.commands]
    assert HCI_INQUIRY_CANCEL in opcodes and HCI_REMOTE_NAME_REQUEST in opcodes
