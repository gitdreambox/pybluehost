"""ble_scan_all: collect all advertisers within the scan window."""
import asyncio
import struct

from pybluehost.cli.app.mitm.recon import ScanEntry, ble_scan_all
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCIEvent


def _adv_report(addr6: bytes, addr_type: int, data: bytes, rssi: int = -50,
                event_type: int = 0x00) -> HCIEvent:
    """Build a LE_Advertising_Report event containing a single report."""
    body = bytes([0x01, event_type, addr_type]) + addr6 \
        + bytes([len(data)]) + data + struct.pack("<b", rssi)
    evt = HCI_LE_Meta_Event.from_bytes(
        EventCode.LE_META, bytes([0x02]) + body
    )
    return evt


class FakeScanController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.commands: list = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.commands.append(command)

    def feed(self, event):
        self._on_hci_event(event)


async def test_collects_all_advertisers_and_merges_scan_rsp():
    ctl = FakeScanController()
    task = asyncio.ensure_future(ble_scan_all(ctl, window=0.2))
    await asyncio.sleep(0.05)  # let the scan start up
    # Device A: ADV (with name)
    a = bytes.fromhex("AABBCCDDEEFF")
    ctl.feed(_adv_report(a, 0, b"\x06\x09Dev-A"))
    # Device B: ADV first, then SCAN_RSP (name in rsp)
    b = bytes.fromhex("112233445566")
    ctl.feed(_adv_report(b, 1, b"\x02\x01\x05"))
    ctl.feed(_adv_report(b, 1, b"\x06\x09Dev-B", event_type=0x04))
    entries = await asyncio.wait_for(task, 2.0)

    addrs = {e.identity.address: e for e in entries}
    assert set(addrs) == {"FF:EE:DD:CC:BB:AA", "66:55:44:33:22:11"}
    assert addrs["FF:EE:DD:CC:BB:AA"].identity.name == "Dev-A"
    assert addrs["66:55:44:33:22:11"].identity.name == "Dev-B"  # ADV+RSP merged
    assert addrs["66:55:44:33:22:11"].rssi == -50
    # scan is disabled when done (set scan enable parameters 0,0)
    assert ctl.commands[-1].parameters == bytes([0x00, 0x00])


async def test_window_with_no_devices_returns_empty():
    ctl = FakeScanController()
    entries = await asyncio.wait_for(ble_scan_all(ctl, window=0.1), 2.0)
    assert entries == []


def _entry(addr: str, rssi):
    from pybluehost.cli.app.mitm.recon import ClonedIdentity
    return ScanEntry(identity=ClonedIdentity(
        address=addr, address_type=0, adv_data=b"", scan_response=b"",
        name=None, class_of_device=None), rssi=rssi)


def test_sorted_by_rssi_desc_and_none_is_weakest():
    """scan list ordering: RSSI descending; entries without RSSI are sorted
    last (treated as -127); the original list is not modified."""
    from pybluehost.cli.app.mitm.cli import _sorted_by_rssi

    entries = [_entry("AA:AA:AA:AA:AA:01", -60), _entry("AA:AA:AA:AA:AA:02", None),
               _entry("AA:AA:AA:AA:AA:03", -40), _entry("AA:AA:AA:AA:AA:04", -80)]
    out = _sorted_by_rssi(entries)
    assert [e.rssi for e in out] == [-40, -60, -80, None]
    # None values keep stable order among themselves; original list unchanged
    assert [e.rssi for e in entries] == [-60, None, -40, -80]
