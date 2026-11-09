"""Tests for BLE GAP: Advertiser, Scanner, ConnectionManager, WhiteList, ExtendedAdvertiser."""
from __future__ import annotations
import asyncio

import pytest

from pybluehost.ble.gap import (
    AdvertisingConfig,
    BLEAdvertiser,
    BLEConnection,
    BLEConnectionManager,
    BLEScanner,
    ConnectionRole,
    ExtAdvertisingConfig,
    ExtendedAdvertiser,
    PERIODIC_ADV_HANDLE,
    PeriodicAdvertising,
    PrivacyManager,
    ScanConfig,
    ScanResult,
    WhiteList,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import (
    HCI_LE_ADD_DEVICE_TO_WHITE_LIST,
    HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST,
    HCI_LE_CLEAR_WHITE_LIST,
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_EXTENDED_CREATE_CONNECTION,
    HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC,
    HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC,
    HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS,
    HCI_LE_SET_PERIODIC_ADVERTISING_DATA,
    HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER,
    HCI_LE_SET_PERIODIC_ADVERTISING_ENABLE,
    HCI_LE_SET_PERIODIC_ADVERTISING_PARAMS,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_ENABLE,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_SET_EXTENDED_ADVERTISING_DATA,
    HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE,
    HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS,
    HCI_LE_SET_EXTENDED_SCAN_ENABLE,
    HCI_LE_SET_EXTENDED_SCAN_PARAMS,
    HCI_LE_SET_EXTENDED_SCAN_RSP_DATA,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_Command_Complete_Event, HCI_LE_Meta_Event
from pybluehost.hci.constants import ErrorCode


class FakeHCI:
    """Minimal HCI mock that records commands and returns success."""

    def __init__(self, capabilities: set[int] | None = None) -> None:
        self.commands: list = []
        # None means "controller says nothing" — the legacy initiator path,
        # which is all a BT 4.0 adapter has.
        self.supported_commands = (
            None if capabilities is None else _FakeSupportedCommands(capabilities)
        )

    async def send_command(self, cmd: object) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )


class _FakeSupportedCommands:
    def __init__(self, capabilities: set[int]) -> None:
        self._capabilities = capabilities

    def has(self, opcode: int) -> bool:
        return opcode in self._capabilities


class _FakeScanner:
    """Stands in for BLEScanner where only the start/stop/active contract matters."""

    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1
        self.active = True

    async def stop(self) -> None:
        self.stopped += 1
        self.active = False


# ---------------------------------------------------------------------------
# BLEAdvertiser
# ---------------------------------------------------------------------------

async def test_advertiser_start_sends_hci_commands():
    """Advertising goes out through the EXTENDED command family.

    Core §3.1.1: issuing a legacy advertising command and then an extended one
    (or vice versa) within a power cycle earns Command Disallowed, and Table
    3.2 covers the periodic advertising commands — so nothing on this path may
    use the legacy commands, or GAP/PADV can never work.
    """
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Test")
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    opcodes = [cmd.opcode for cmd in hci.commands]
    assert HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS in opcodes
    assert HCI_LE_SET_EXTENDED_ADVERTISING_DATA in opcodes
    assert HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE in opcodes


async def test_advertiser_start_uses_legacy_pdu_properties():
    """Table 7.3: properties must keep the on-air PDUs identical to what the
    legacy command produced (bit 4) and match the requested adv_type."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.start(AdvertisingConfig(adv_type=0x02), ad_data=AdvertisingData())
    cmd = next(c for c in hci.commands if c.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS)
    assert cmd.parameters[0] == 0x00                        # advertising handle
    assert int.from_bytes(cmd.parameters[1:3], "little") == 0x0012   # ADV_SCAN_IND
    assert len(cmd.parameters) == 25                        # Core §7.8.53
    assert cmd.parameters[20] == 0x01                       # primary PHY = LE 1M
    assert cmd.parameters[22] == 0x01                       # secondary PHY


async def test_advertiser_reports_the_random_address_it_advertises_with():
    """The controller never reports a host-programmed random address back, so
    the advertiser must remember it: SMP hashes the address the peer saw."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.set_random_address(bytes.fromhex("1a5bdb10da70"))
    await advertiser.start(AdvertisingConfig(own_address_type=0x01))

    assert advertiser.advertising_address == bytes.fromhex("1a5bdb10da70")


async def test_advertiser_has_no_random_address_when_advertising_public():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.set_random_address(bytes.fromhex("1a5bdb10da70"))
    await advertiser.start(AdvertisingConfig(own_address_type=0x00))

    assert advertiser.advertising_address is None


async def test_advertiser_directed_types_carry_no_advertising_data():
    """Table 7.3: directed advertising is not allowed to carry AD, and §7.8.53
    answers 0x12 if such a type is set on a set that already holds data."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.start(AdvertisingConfig(adv_type=0x01), ad_data=AdvertisingData())
    assert [c.opcode for c in hci.commands] == [
        HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS,
        HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE,
    ]


async def test_advertiser_start_sends_scan_response_data():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    scan_rsp = AdvertisingData()
    scan_rsp.set_complete_local_name("PyBlueHost HR")

    await advertiser.start(config=AdvertisingConfig(), ad_data=AdvertisingData(), scan_rsp_data=scan_rsp)

    scan_rsp_cmd = next(cmd for cmd in hci.commands if cmd.opcode == HCI_LE_SET_EXTENDED_SCAN_RSP_DATA)
    assert scan_rsp_cmd.parameters[:4] == bytes([0x00, 0x03, 0x00, len(scan_rsp.to_bytes())])
    assert b"PyBlueHost HR" in scan_rsp_cmd.parameters


async def test_advertiser_data_commands_omit_nothing_from_the_header():
    """Core §7.8.54/§7.8.55: the header is handle, operation,
    Fragment_Preference, Advertising_Data_Length — four bytes, not three.

    Dropping Fragment_Preference shifts every following byte by one, so the
    controller reads our *data length* as the fragment preference and our
    first AD byte as the length. It answers 0x00 either way and then puts a
    two-byte AD on air — a failure that is invisible from the Host side.
    """
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    ad.set_flags(0x04)
    ad.set_complete_local_name("Tester_0704EE")
    scan_rsp = AdvertisingData()
    scan_rsp.set_complete_local_name("PyBlueHost HR")
    expected_ad = ad.to_bytes()

    await advertiser.start(config=AdvertisingConfig(), ad_data=ad, scan_rsp_data=scan_rsp)

    for opcode, raw in (
        (HCI_LE_SET_EXTENDED_ADVERTISING_DATA, expected_ad),
        (HCI_LE_SET_EXTENDED_SCAN_RSP_DATA, scan_rsp.to_bytes()),
    ):
        cmd = next(c for c in hci.commands if c.opcode == opcode)
        assert cmd.parameters[:4] == bytes([0x00, 0x03, 0x00, len(raw)]), hex(opcode)
        assert cmd.parameters[4:] == raw, hex(opcode)
        assert len(cmd.parameters) == 4 + len(raw), hex(opcode)


async def test_advertiser_writes_scan_response_before_advertising_data():
    """The scan-response write must come *first*, or an empty one wipes the AD.

    On the Intel BE200 an LE_Set_Extended_Scan_Response_Data with
    Scan_Response_Data_Length == 0 clears the whole set's data — the command
    still answers 0x00 and the set then advertises the correct PDU type from
    the correct address carrying a zero-length AdvData. Measured with a second
    dongle as a passive observer, one variant per advertising start:

        params, data, scan-rsp(len 0), enable  -> observed ad_len=0
        params, data, enable                   -> observed ad_len=14
        params, data, scan-rsp(len 14), enable  -> observed ad_len=14
        params, scan-rsp(len 0), data, enable   -> observed ad_len=14

    Nothing in Core §7.8.55 allows the scan-response buffer to touch the
    advertising data, so this is a controller quirk, not a spec behaviour we
    should rely on — but the ordering it forces is free, so we take it.
    """
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.start(config=AdvertisingConfig(), ad_data=AdvertisingData())

    opcodes = [c.opcode for c in hci.commands]
    scan_rsp = opcodes.index(HCI_LE_SET_EXTENDED_SCAN_RSP_DATA)
    adv_data = opcodes.index(HCI_LE_SET_EXTENDED_ADVERTISING_DATA)
    assert scan_rsp < adv_data


async def test_advertiser_stop_disables_only_its_own_set():
    """Periodic advertising lives on its own set (PERIODIC_ADV_HANDLE), so the
    GAP stop must not use the "disable all sets" form."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    hci.commands.clear()
    await advertiser.stop()
    assert len(hci.commands) == 1
    cmd = hci.commands[0]
    assert cmd.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
    assert cmd.parameters == bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x00])


async def test_advertiser_stop_without_start_is_a_no_op():
    """A per-set disable of a set that was never enabled is rejected (0x12)."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.stop()
    assert hci.commands == []


async def test_advertiser_programs_the_set_random_address_after_creating_it():
    """With the extended commands in use LE_Set_Random_Address only reaches
    scanning and initiating; the set draws its address from
    LE_Set_Advertising_Set_Random_Address (Core §7.8.5 note), and only once the
    set exists (0x42 otherwise) — so it has to follow the parameters command."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    address = bytes.fromhex("6b f5 1b 8d 8d 1a")
    assert await advertiser.set_random_address(address) is True

    hci.commands.clear()
    await advertiser.start(AdvertisingConfig(own_address_type=0x01), ad_data=AdvertisingData())

    ops = [c.opcode for c in hci.commands]
    set_addr = hci.commands[ops.index(HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS)]
    assert set_addr.parameters == bytes([0x00]) + address
    assert ops.index(HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS) > ops.index(
        HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS
    )


async def test_advertiser_skips_the_set_address_for_public_advertising():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    await advertiser.set_random_address(bytes.fromhex("6b f5 1b 8d 8d 1a"))
    hci.commands.clear()
    await advertiser.start(AdvertisingConfig(own_address_type=0x00), ad_data=AdvertisingData())
    assert HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS not in [c.opcode for c in hci.commands]


# ---------------------------------------------------------------------------
# BLEScanner
# ---------------------------------------------------------------------------

async def test_scanner_delivers_results():
    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))
    await scanner.start()
    report = ScanResult(
        address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"),
        rssi=-70,
        advertising_data=AdvertisingData(),
        connectable=True,
    )
    await scanner._on_advertising_report(report)
    assert len(results) == 1
    assert results[0].rssi == -70


async def test_scanner_parses_legacy_le_advertising_report():
    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))

    ad = AdvertisingData()
    ad.set_complete_local_name("PBH")
    raw_ad = ad.to_bytes()
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_ADVERTISING_REPORT,
        subevent_parameters=(
            b"\x01"  # Num reports
            b"\x00"  # ADV_IND
            b"\x00"  # Public address
            b"\x6b\xf5\x1b\x8d\x8d\x1a"
            + bytes([len(raw_ad)])
            + raw_ad
            + bytes([0xD6])  # -42 dBm
        ),
    )

    await scanner.on_hci_event(event)
    # The report is held briefly so a scan response can join it
    # (_on_legacy_advertising_report), then emitted once.
    await asyncio.sleep(scanner._MERGE_WINDOW_S + 0.1)

    assert len(results) == 1
    assert str(results[0].address) == "1A:8D:8D:1B:F5:6B"
    assert results[0].rssi == -42
    assert results[0].local_name == "PBH"


async def test_scanner_merges_the_scan_response_into_one_report():
    """A device's advertising data and its scan response arrive as two reports
    (event type 0x00 and 0x04) and must be reported as ONE EIR.

    auto-pts appends one LeAdv per DEVICE_FOUND event and its
    scan-report-and-response check compares one device against both halves, so
    forwarding the reports separately made GAP/BROB/OBSV/BV-05/06 fail its
    confirmation WID.
    """
    import asyncio

    from pybluehost.hci.constants import LEMetaSubEvent

    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))

    ad = AdvertisingData()
    ad.set_complete_local_name("PBH")
    scan_rsp = bytes.fromhex("1324" + "2f2f626c7565746f6f74682e636f6d" + "0d0a")
    address = b"\x6b\xf5\x1b\x8d\x8d\x1a"

    def _report(event_type: int, payload: bytes) -> HCI_LE_Meta_Event:
        return HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_ADVERTISING_REPORT,
            subevent_parameters=(
                b"\x01" + bytes([event_type]) + b"\x00" + address
                + bytes([len(payload)]) + payload + bytes([0xD6])
            ),
        )

    await scanner.on_hci_event(_report(0x00, ad.to_bytes()))
    await scanner.on_hci_event(_report(0x04, scan_rsp))
    await asyncio.sleep(0.1)

    assert len(results) == 1, "one device, one report"
    merged = results[0].advertising_data
    assert merged.get_complete_local_name() == "PBH"
    # The raw EIR is what the BTP event carries: AdvertisingData drops AD types
    # it does not model, so to_bytes() would lose the URI structure.
    assert results[0].raw_advertising_data == ad.to_bytes() + scan_rsp


def _ext_report_params(event_type: int, payload: bytes, *,
                       address: bytes = b"\x6b\xf5\x1b\x8d\x8d\x1a",
                       rssi: int = 0xD6) -> bytes:
    """One extended report as the wire carries it (§7.7.65.13).

    Event_Type is *two* octets; the fixed per-report header is 24 bytes and
    RSSI sits inside it (unlike the legacy subevent, which trails RSSI after
    the data). Verified against 1008 on-air BE200 captures — the WQ_7035/JBL
    events decode to sane RSSI/SID/TX_Power only under this layout.
    """
    return (
        b"\x01"                     # Num_Reports
        + event_type.to_bytes(2, "little")
        + b"\x00" + address         # Addr_Type (public) + Address
        + b"\x01\x00"               # Primary_PHY 1M, Secondary_PHY none
        + b"\x00\x7f"               # SID 0, TX_Power unavailable
        + bytes([rssi & 0xFF])      # RSSI
        + b"\x00\x00"               # Periodic_Advertising_Interval: none
        + b"\x00" + bytes(6)        # Direct_Address_Type + Direct_Address
        + bytes([len(payload)]) + payload
    )


async def test_scanner_parses_the_extended_advertising_report():
    """Scanning with the extended family reports even legacy advertisers
    through LE_Extended_Advertising_Report — with Event_Type bit 4 set.

    The scanner used to debug-log that subevent and return, so once it moved to
    LE_Set_Extended_Scan_* no device would ever have reached on_result.
    """
    import asyncio

    from pybluehost.hci.constants import LEMetaSubEvent

    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))

    ad = AdvertisingData()
    ad.set_complete_local_name("PBH")
    raw_ad = ad.to_bytes()
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_EXTENDED_ADVERTISING_REPORT,
        subevent_parameters=_ext_report_params(0x0013, raw_ad, rssi=0xD6),
    )

    await scanner.on_hci_event(event)
    await asyncio.sleep(scanner._MERGE_WINDOW_S + 0.1)

    assert len(results) == 1
    assert str(results[0].address) == "1A:8D:8D:1B:F5:6B"
    assert results[0].rssi == -42
    assert results[0].local_name == "PBH"
    assert results[0].raw_advertising_data == raw_ad
    assert results[0].connectable is True


async def test_scanner_merges_the_extended_scan_response():
    """The extended layout's scan-response bit is bit 3, not bit 2.

    BlueZ's LE_EXT_ADV_SCAN_RSP is 0x0008 and bit 2 is *directed* — testing
    0x04 here would misfile a legacy ADV_DIRECT_IND (0x15) as a scan response
    and hand auto-pts a garbled EIR split across two events.
    """
    import asyncio

    from pybluehost.hci.constants import LEMetaSubEvent

    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))

    ad = AdvertisingData()
    ad.set_complete_local_name("PBH")
    scan_rsp = bytes.fromhex("1324" + "2f2f626c7565746f6f74682e636f6d" + "0d0a")

    def _report(event_type: int, payload: bytes) -> HCI_LE_Meta_Event:
        return HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_EXTENDED_ADVERTISING_REPORT,
            subevent_parameters=_ext_report_params(event_type, payload),
        )

    await scanner.on_hci_event(_report(0x13, ad.to_bytes()))   # ADV_IND
    await scanner.on_hci_event(_report(0x1A, scan_rsp))        # legacy SCAN_RSP
    await asyncio.sleep(0.1)

    assert len(results) == 1, "one device, one report"
    assert results[0].local_name == "PBH"
    assert results[0].raw_advertising_data == ad.to_bytes() + scan_rsp


async def test_scanner_does_not_mistake_directed_advertising_for_a_scan_response():
    """ADV_DIRECT_IND is Event_Type 0x15 in the extended layout; bit 2 is set
    but it is a *directed* advertisement, not a scan response."""
    import asyncio

    from pybluehost.hci.constants import LEMetaSubEvent

    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    results: list[ScanResult] = []
    scanner.on_result(lambda r: results.append(r))

    payload = bytes.fromhex("020106")
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_EXTENDED_ADVERTISING_REPORT,
        subevent_parameters=_ext_report_params(0x0015, payload),
    )

    await scanner.on_hci_event(event)
    await asyncio.sleep(scanner._MERGE_WINDOW_S + 0.1)

    assert len(results) == 1
    assert results[0].raw_advertising_data == payload
    assert results[0].connectable is True


async def test_extended_report_parser_bails_out_on_truncation():
    """A short subevent must be dropped, not unpacked past its end."""
    from pybluehost.ble.gap import _parse_extended_advertising_reports

    body = (
        bytes([2])                       # two reports promised
        + b"\x13\x00" + bytes.fromhex("aabbccddeeff")
        + b"\x01\x00\x00\x7f\xd6" + b"\x00\x00"
        + b"\x00" + bytes(6) + bytes([3]) + bytes.fromhex("020106")
    )
    # Only the first report fits: the second is truncated mid-header.
    assert len(list(_parse_extended_advertising_reports(body + b"\x13"))) == 1
    assert list(_parse_extended_advertising_reports(body[:20])) == []
    assert list(_parse_extended_advertising_reports(b"")) == []


async def test_extended_report_parser_replays_the_captured_lt_rpa_event():
    """Byte-for-byte replay of the GAP/DISC/RPA/BV-01-C LT report.

    The parser used to read Event_Type as one octet (§7.7.65.13 gives it
    two), shifting every later field by one: the address swallowed the
    address-type byte, Data_Length landed inside Direct_Address, and this
    report arrived as a garbled non-device — INDCSV with no visible cause.
    """
    from pybluehost.ble.gap import _parse_extended_advertising_reports

    ad_data = bytes.fromhex("0201020c095054532d4741502d303031")  # flags+"PTS-GAP-001"
    params = (
        b"\x01"                         # Num_Reports
        b"\x12\x00"                     # Event_Type 0x0012: scannable + legacy PDU
        b"\x01"                         # Addr_Type: random
        b"\x28\x03\x01\xd3\x68\x47"     # Address (wire LE; display 47:68:D3:01:03:28)
        b"\x01"                         # Primary_PHY: LE 1M
        b"\x00"                         # Secondary_PHY: none (legacy PDU)
        b"\xff"                         # SID: n/a for a legacy PDU
        b"\x7f"                         # TX_Power: unavailable
        b"\xcf"                         # RSSI: -49
        b"\x00\x00"                     # Periodic_Advertising_Interval: none
        b"\x00" + bytes(6)              # Direct_Address_Type + Direct_Address
        + bytes([len(ad_data)]) + ad_data
    )

    (report,) = list(_parse_extended_advertising_reports(params))
    assert report.address == bytes.fromhex("280301d36847")
    assert report.address_type == 1
    assert report.event_type == 0x0012
    assert report.rssi == -49
    assert report.ad_data == ad_data
    assert report.connectable is False
    assert report.is_scan_response is False


async def test_scanner_stop():

    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)
    await scanner.start()
    hci.commands.clear()
    await scanner.stop()
    assert len(hci.commands) >= 1  # Should send LE_Set_Scan_Enable(disable)


# ---------------------------------------------------------------------------
# WhiteList
# ---------------------------------------------------------------------------

async def test_whitelist_add_device():
    hci = FakeHCI()
    wl = WhiteList(hci=hci)
    addr = BDAddress.from_string("1A:8D:8D:1B:F5:6B")
    await wl.add(addr, address_type=0x00)
    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_ADD_DEVICE_TO_WHITE_LIST
    assert cmd.parameters == bytes([0x00]) + bytes.fromhex("6b f5 1b 8d 8d 1a")


async def test_whitelist_clear():
    hci = FakeHCI()
    wl = WhiteList(hci=hci)
    await wl.clear()
    assert HCI_LE_CLEAR_WHITE_LIST in [cmd.opcode for cmd in hci.commands]


# ---------------------------------------------------------------------------
# ExtendedAdvertiser
# ---------------------------------------------------------------------------

async def test_extended_advertiser_create_set():
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    config = ExtAdvertisingConfig(adv_handle=0, primary_phy=1, secondary_phy=1, adv_type=0x05)
    await ext_adv.create_set(config)
    assert HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS in [cmd.opcode for cmd in hci.commands]


async def test_extended_advertiser_start():
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    await ext_adv.start(handles=[0], durations=None)
    assert HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE in [cmd.opcode for cmd in hci.commands]


# ---------------------------------------------------------------------------
# BLEConnection
# ---------------------------------------------------------------------------

def test_ble_connection_dataclass():
    conn = BLEConnection(
        handle=0x0040,
        peer_address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"),
        role=ConnectionRole.CENTRAL,
    )
    assert conn.handle == 0x0040
    assert conn.att is None
    assert conn.role == ConnectionRole.CENTRAL


# ---------------------------------------------------------------------------
# PrivacyManager
# ---------------------------------------------------------------------------

def test_privacy_manager_resolve_rpa():
    """An RPA generated by generate_rpa resolves against the IRK that made it,
    and not against any other key. (Round-trip only — the on-air convention is
    pinned by the hardware PTS run.)"""
    irk = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    rpa_bytes = PrivacyManager.generate_rpa(irk, random_bytes=bytes.fromhex("708194"))

    assert PrivacyManager.resolve_rpa(rpa_bytes, irk) is True
    # Wrong IRK should fail
    assert PrivacyManager.resolve_rpa(rpa_bytes, bytes(16)) is False


# ---------------------------------------------------------------------------
# BLEConnectionManager
# ---------------------------------------------------------------------------

def test_connection_manager_construction():
    hci = FakeHCI()
    mgr = BLEConnectionManager(hci=hci)
    assert mgr is not None


async def test_connection_manager_connect_packs_le_create_connection():
    hci = FakeHCI()
    mgr = BLEConnectionManager(hci=hci)
    target = BDAddress.from_string("A0:90:B5:10:40:82")

    await mgr.connect(target)

    assert hci.commands[-1].opcode == HCI_LE_CREATE_CONNECTION
    assert len(hci.commands[-1].parameters) == 25
    assert hci.commands[-1].parameters[6:12] == bytes.fromhex("82 40 10 b5 90 a0")


async def test_connection_manager_connect_prefers_extended_initiator():
    """A controller advertising 0x2043 must be driven with it: while an
    extended advertising set exists, 0x200D answers Command Disallowed and
    stays disallowed until HCI_Reset, so GAP/PADV/PAST can never connect."""
    hci = FakeHCI(capabilities={HCI_LE_EXTENDED_CREATE_CONNECTION})
    mgr = BLEConnectionManager(hci=hci)
    target = BDAddress.from_string("A0:90:B5:10:40:82")

    await mgr.connect(target)

    params = hci.commands[-1].parameters
    assert hci.commands[-1].opcode == HCI_LE_EXTENDED_CREATE_CONNECTION
    assert len(params) == 26
    assert params[0] == 0x00                      # initiator filter policy
    assert params[1] == 0x00                      # own address type
    assert params[2] == target.type               # peer address type
    assert params[3:9] == bytes.fromhex("82 40 10 b5 90 a0")
    assert params[9] == 0x01                      # initiating PHYs: LE 1M
    # Scan_Interval, Scan_Window, then the four connection parameters.
    assert params[10:12] == (0x0060).to_bytes(2, "little")   # 60 ms
    assert params[12:14] == (0x0030).to_bytes(2, "little")   # 30 ms
    assert params[14:16] == (24).to_bytes(2, "little")       # 30 ms
    assert params[16:18] == (40).to_bytes(2, "little")       # 50 ms
    assert params[18:20] == (0x0000).to_bytes(2, "little")   # latency
    assert params[20:22] == (0x01F4).to_bytes(2, "little")   # 5 s
    assert params[22:26] == bytes(4)              # min/max CE length


async def test_connection_manager_connect_falls_back_without_extended_initiator():
    """BT 4.0/4.1 controllers (CSR8510 and friends) lack 0x2043 — they must
    still get the legacy 25-octet command, not a rejected one."""
    hci = FakeHCI(capabilities=set())
    mgr = BLEConnectionManager(hci=hci)
    target = BDAddress.from_string("A0:90:B5:10:40:82")

    await mgr.connect(target)

    assert hci.commands[-1].opcode == HCI_LE_CREATE_CONNECTION
    assert len(hci.commands[-1].parameters) == 25


# ---------------------------------------------------------------------------
# PeriodicAdvertising (GAP/PADV — PTS opcodes 0x22-0x29)
# ---------------------------------------------------------------------------

async def test_periodic_advertising_configure_sends_params():
    """LE_Set_Periodic_Advertising_Parameters: handle, interval min/max, props.
    include_tx_power sets the Properties bit 0x0040 (Core §7.8.61)."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.configure(include_tx_power=True, interval_min=0x0010, interval_max=0x0020)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_PERIODIC_ADVERTISING_PARAMS
    assert cmd.parameters == bytes([PERIODIC_ADV_HANDLE, 0x10, 0x00, 0x20, 0x00, 0x40, 0x00])


async def test_periodic_advertising_set_data_pads_to_252():
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    # Payload length must differ from the Operation value 0x03: with a
    # three-octet payload a dropped Operation byte leaves the command
    # byte-identical, because 0x03 is both "complete data" and a length.
    await padv.set_data(b"\x01\x02\x03\x04\x05")

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_PERIODIC_ADVERTISING_DATA
    assert len(cmd.parameters) == 255
    assert cmd.parameters[0] == PERIODIC_ADV_HANDLE
    assert cmd.parameters[1] == 0x03            # operation: complete data
    assert cmd.parameters[2] == 0x05            # data length
    assert cmd.parameters[3:8] == b"\x01\x02\x03\x04\x05"
    assert cmd.parameters[8:] == bytes(247)     # zero-padded to 252


async def test_periodic_advertising_start_and_stop_toggle_enable_bit():
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.start()
    assert hci.commands[-1].opcode == HCI_LE_SET_PERIODIC_ADVERTISING_ENABLE
    assert hci.commands[-1].parameters == bytes([0x01, PERIODIC_ADV_HANDLE])

    await padv.stop()
    assert hci.commands[-1].parameters == bytes([0x00, PERIODIC_ADV_HANDLE])


async def test_periodic_advertising_set_info_transfer_body():
    """LE_Periodic_Advertising_Set_Info_Transfer: the *source* direction.

    Vol 4 Part E §7.8.90 — Connection_Handle(2) + Service_Data(2) +
    Advertising_Handle(1), 5 octets, and the only PAST command in the family
    that puts synchronization information on air for a peer we are merely
    connected to (the §7.8.89/7.8.91/7.8.92 neighbours are the re-transfer and
    sink directions and send nothing here). GAP/PADV/PAST answered every WID
    Ok and then went silent for 30 s precisely because this command was never
    issued.
    """
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.set_info_transfer(conn_handle=0x0E01, service_data=0x1234)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER
    assert cmd.opcode == 0x205B
    assert cmd.parameters == bytes([0x01, 0x0E, 0x34, 0x12, PERIODIC_ADV_HANDLE])


async def test_periodic_sync_create_sync_params():
    """LE_Periodic_Advertising_Create_Sync: Options, SID, addr type + addr,
    Skip, Sync_Timeout, Sync_CTE_Type."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.create_sync(
        adv_sid=0x02, skip=0x0003, sync_timeout=0x0BB8, flags=0x00,
        address_type=0x01, address=bytes.fromhex("ee 6a 1e ff 53 94"),
    )

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC
    assert cmd.parameters == (
        bytes([0x00, 0x02, 0x01]) + bytes.fromhex("ee6a1eff5394")
        + bytes([0x03, 0x00, 0xB8, 0x0B, 0x00])
    )


async def test_periodic_sync_create_sync_maps_btp_flags_to_hci_options():
    """The BTP flag byte and the HCI Options byte do NOT share a layout.

    BTP (doc/btp_gap.txt opcode 0x26): bit 0 = Reports Disabled, bit 1 =
    Duplicate filtering enabled. HCI §7.8.67: bit 0 = "use the Periodic
    Advertiser List", bit 1 = "reporting initially disabled", bit 2 =
    "duplicate filtering initially enabled".

    Copying bit 0 straight across — the old behaviour — made every WID that
    asked for reports-disabled (WID 303) select the advertiser *list* instead
    of the address parameters, so the sync silently never established.
    """
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    address = bytes.fromhex("ee 6a 1e ff 53 94")

    async def options_for(flags: int) -> int:
        await padv.create_sync(
            adv_sid=0x00, skip=0x0000, sync_timeout=0x01F4, flags=flags,
            address_type=0x00, address=address,
        )
        return hci.commands[-1].parameters[0]

    assert await options_for(0x00) == 0x00   # reports enabled, no dup filter
    assert await options_for(0x01) == 0x02   # reports disabled
    assert await options_for(0x02) == 0x04   # duplicate filtering enabled
    assert await options_for(0x03) == 0x06   # both

    # The address parameters must survive every mapping — bit 0 of Options
    # would otherwise mean "ignore these and use the Periodic Advertiser List".
    assert hci.commands[-1].parameters[3:9] == address


async def test_periodic_sync_create_sync_enables_scanning_first():
    """§7.8.67: "synchronization can only occur when scanning is enabled.
    While scanning is disabled, no attempt to synchronize will take place."

    The command is accepted either way, so a controller whose scan is off
    answers 0x00 and then emits nothing — no Sync Established, no error. The
    GAP.TS initial condition for GAP/PADV/PASE is Link Layer Standby, so the
    Host has to enable the scan itself or the case can only ever time out.

    It has to be the *extended* scan: §7.8.11 says LE_Set_Scan_Enable "is used
    to start and stop scanning for legacy PDUs (but not extended PDUs, even if
    the device supports extended advertising)", and a periodic train rides on
    AUX_SYNC_IND — an extended PDU. A legacy scan leaves the controller blind
    to it, which on air is indistinguishable from "accepted, then nothing".
    """
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.create_sync(
        adv_sid=0x00, skip=0x0000, sync_timeout=0x01F4, flags=0x01,
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
    )

    opcodes = [cmd.opcode for cmd in hci.commands]
    assert opcodes == [
        HCI_LE_SET_EXTENDED_SCAN_PARAMS, HCI_LE_SET_EXTENDED_SCAN_ENABLE,
        HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC,
    ]
    # Enable=0x01, Filter_Duplicates=0x01, Duration=0, Period=0 (§7.8.65).
    assert hci.commands[1].parameters == bytes([0x01, 0x01]) + bytes(4)
    params = hci.commands[0].parameters
    # Own_Address_Type, Scanning_Filter_Policy, Scanning_PHYs(=LE 1M, bit 0),
    # then one 5-byte [Scan_Type, Interval, Window] set per advertised PHY bit.
    interval = int(ScanConfig().interval_ms / 0.625)
    # 100% duty — the train is on its channel for a sliver of each interval.
    per_phy = bytes([0x00]) + interval.to_bytes(2, "little") * 2
    assert params == bytes([0x00, 0x00, 0x01]) + per_phy + per_phy


async def test_periodic_sync_create_sync_leaves_an_active_scan_alone():
    """A scan the application owns is left untouched: it already covers the
    air, and stopping it would break whatever the application is doing."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    scanner = _FakeScanner(active=True)
    padv.bind_scanner(scanner)

    await padv.create_sync(
        adv_sid=0x00, skip=0x0000, sync_timeout=0x01F4, flags=0x00,
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
    )

    assert scanner.started == 0
    assert [cmd.opcode for cmd in hci.commands] == [
        HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC
    ]

    await padv.terminate_sync(0x0001)
    assert scanner.stopped == 0


async def test_periodic_sync_create_sync_does_not_drive_the_bound_scanner():
    """A bound-but-idle scanner is not borrowed for the sync scan.

    The application's scanner uses the legacy commands, which cannot see an
    extended PDU at all, and starting it would also leave the application
    believing it owns the scan engine. The sync side writes the two extended
    HCI commands itself and leaves the bound scanner alone.
    """
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    scanner = _FakeScanner(active=False)
    padv.bind_scanner(scanner)

    await padv.create_sync(
        adv_sid=0x00, skip=0x0000, sync_timeout=0x01F4, flags=0x00,
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
    )

    assert scanner.started == 0
    assert [cmd.opcode for cmd in hci.commands] == [
        HCI_LE_SET_EXTENDED_SCAN_PARAMS, HCI_LE_SET_EXTENDED_SCAN_ENABLE,
        HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC,
    ]

    await padv.terminate_sync(0x0001)
    assert scanner.stopped == 0
    assert hci.commands[-1].opcode == HCI_LE_SET_EXTENDED_SCAN_ENABLE


async def test_periodic_sync_terminate_releases_only_its_own_scan():
    """terminate_sync stops the scan it enabled, and only that one."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    # Never started a sync scan — nothing to release.
    await padv.terminate_sync(0x0001)
    assert HCI_LE_SET_EXTENDED_SCAN_ENABLE not in [
        cmd.opcode for cmd in hci.commands
    ]

    await padv.create_sync(
        adv_sid=0x00, skip=0x0000, sync_timeout=0x01F4, flags=0x00,
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
    )
    await padv.terminate_sync(0x0001)

    assert [cmd.opcode for cmd in hci.commands] == [
        HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC,
        HCI_LE_SET_EXTENDED_SCAN_PARAMS, HCI_LE_SET_EXTENDED_SCAN_ENABLE,
        HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC,
        HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC,
        HCI_LE_SET_EXTENDED_SCAN_ENABLE,
    ]
    assert hci.commands[-1].parameters == bytes([0x00, 0x00]) + bytes(4)


async def test_periodic_sync_established_event_populates_sync():
    """LE Periodic Advertising Sync Established (subevent 0x0E, §7.7.65.14)
    drives the on_sync_established hook that the BTP service turns into 0x8d."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    seen: list = []
    padv.set_handlers(on_sync_established=seen.append)

    params = (
        bytes([0x00])                      # status success
        + bytes([0x34, 0x12])              # sync handle 0x1234
        + bytes([0x05, 0x01])              # SID 5, addr type 1
        + bytes.fromhex("ee6a1eff5394")
        + bytes([0x01])                    # PHY = LE 1M
        + bytes([0x20, 0x00])              # interval
        + bytes([0x00])                    # clock accuracy
    )
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
        subevent_parameters=params,
    )
    await padv.on_hci_event(event)

    assert len(seen) == 1
    assert seen[0].sync_handle == 0x1234
    assert seen[0].adv_sid == 0x05
    assert seen[0].interval == 0x0020
    assert padv.sync is not None


async def test_periodic_sync_established_failure_status_is_ignored():
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    seen: list = []
    padv.set_handlers(on_sync_established=seen.append)

    params = bytes([0x3E]) + bytes(14)  # non-zero status
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
        subevent_parameters=params,
    )
    await padv.on_hci_event(event)

    assert seen == []
    assert padv.sync is None


async def test_periodic_report_event_extracts_advertising_data():
    """The report carries a 7-byte header ending in Data_Length, then the data."""
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    seen: list = []
    padv.set_handlers(on_report=seen.append)

    params = (
        bytes([0x34, 0x12])                # sync handle
        + bytes([0x7F, 0xB0])              # tx power, rssi
        + bytes([0x00, 0x00])              # cte type, data status
        + bytes([0x04])                    # data length
        + b"\xaa\xbb\xcc\xdd"
    )
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_PERIODIC_ADVERTISING_REPORT,
        subevent_parameters=params,
    )
    await padv.on_hci_event(event)

    assert seen == [b"\xaa\xbb\xcc\xdd"]


async def test_periodic_sync_lost_event_clears_sync():
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    lost: list = []
    padv.set_handlers(on_sync_lost=lost.append)

    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_LOST,
        subevent_parameters=bytes([0x34, 0x12]),
    )
    await padv.on_hci_event(event)

    assert lost == [0x1234]
    assert padv.sync is None


async def test_periodic_sync_transfer_received_fires_hook():
    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)
    seen: list = []
    padv.set_handlers(on_transfer_received=lambda: seen.append(True))

    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED,
        subevent_parameters=bytes(16),
    )
    await padv.on_hci_event(event)

    assert seen == [True]


async def test_extended_advertiser_create_set_emits_25_byte_params():
    """LE_Set_Extended_Advertising_Parameters is a 25-byte command (Core
    §7.8.53). The previous 5-byte body was rejected by controllers, which broke
    periodic advertising (its set must be created here with extended PDUs)."""
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    config = ExtAdvertisingConfig(
        adv_handle=0, properties=0x0000,
        interval_min=0x000020, interval_max=0x000030,
        primary_phy=1, secondary_phy=1, sid=0x05,
    )

    await ext_adv.create_set(config)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS
    assert len(cmd.parameters) == 25
    assert cmd.parameters[0] == 0x00                       # advertising handle
    assert cmd.parameters[1:3] == bytes([0x00, 0x00])      # properties
    assert cmd.parameters[3:6] == bytes([0x20, 0x00, 0x00])  # interval min (3B LE)
    assert cmd.parameters[6:9] == bytes([0x30, 0x00, 0x00])  # interval max (3B LE)
    assert cmd.parameters[19] == 0x7F                      # Tx_Power: no preference
    assert cmd.parameters[23] == 0x05                      # advertising SID


async def test_extended_advertiser_set_data_declares_fragment_preference():
    """Same header rule as §7.8.54 — see
    test_advertiser_data_commands_omit_nothing_from_the_header."""
    hci = FakeHCI()
    ext_adv = ExtendedAdvertiser(hci=hci)
    ad = AdvertisingData()
    ad.set_flags(0x04)
    ad.set_complete_local_name("Tester_0704EE")
    raw = ad.to_bytes()

    await ext_adv.set_data(0, ad)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_DATA
    assert cmd.parameters[:4] == bytes([0x00, 0x03, 0x00, len(raw)])
    assert cmd.parameters[4:] == raw


# ---------------------------------------------------------------------------
# PrivacyManager — RPA / NRPA generation + controller programming
# ---------------------------------------------------------------------------

def test_nrpa_has_top_two_bits_clear():
    """A non-resolvable private address is 46 random bits: the two most
    significant bits of the most significant octet are 00 (Core §10.8.2.1)."""
    for seed in range(50):
        addr = PrivacyManager.generate_nrpa()
        assert len(addr) == 6
        assert addr[5] & 0xC0 == 0x00
        assert any(b for b in addr)          # never the invalid all-zero address


def test_nrpa_is_random_across_calls():
    seen = {PrivacyManager.generate_nrpa() for _ in range(50)}
    assert len(seen) > 40


def test_rpa_round_trips_against_its_irk():
    """An RPA is hash(3) || prand(3) with the prand top two bits = 01; the
    controller/Lower Tester resolves it with ah(IRK, prand)."""
    irk = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    rpa = PrivacyManager.generate_rpa(irk)

    assert len(rpa) == 6
    prand = rpa[3:6]
    assert prand[2] & 0xC0 == 0x40        # top two bits of the MSB = 01
    assert PrivacyManager.resolve_rpa(rpa, irk) is True
    assert PrivacyManager.resolve_rpa(rpa, bytes(16)) is False


async def test_set_random_address_issues_hci_and_reports_rejection():
    hci = FakeHCI()
    privacy = PrivacyManager(hci=hci)

    ok = await privacy.set_random_address(bytes.fromhex("6b f5 1b 8d 8d 1a"))

    assert ok is True
    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_RANDOM_ADDRESS
    assert cmd.parameters == bytes.fromhex("6b f5 1b 8d 8d 1a")

    class _RejectingHCI(FakeHCI):
        async def send_command(self, cmd):
            self.commands.append(cmd)
            return HCI_Command_Complete_Event(
                num_hci_command_packets=1, command_opcode=cmd.opcode,
                return_parameters=bytes([0x0C]),   # Command Disallowed
            )

    privacy2 = PrivacyManager(hci=_RejectingHCI())
    assert await privacy2.set_random_address(bytes(6)) is False


async def test_add_to_resolving_list_layout():
    hci = FakeHCI()
    privacy = PrivacyManager(hci=hci)
    peer_irk = bytes(range(16))

    await privacy.add_to_resolving_list(bytes.fromhex("ee 6a 1e ff 53 94"), peer_irk)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST
    assert len(cmd.parameters) == 1 + 6 + 16 + 16
    assert cmd.parameters[0] == 0x00
    assert cmd.parameters[1:7] == bytes.fromhex("ee 6a 1e ff 53 94")
    assert cmd.parameters[7:23] == peer_irk


async def test_private_address_rotates_on_the_configured_cadence():
    """TGAP(private_addr_int): the IUT must change a private address on a
    schedule — PTS observes the advertising events (BCST/BV-04)."""
    import asyncio as _asyncio

    hci = FakeHCI()
    privacy = PrivacyManager(hci=hci)
    await privacy.enable()
    await privacy.start_rotation(0.01)
    try:
        await _asyncio.sleep(0.05)
    finally:
        await privacy.stop_rotation()

    set_addr = [c for c in hci.commands if c.opcode == HCI_LE_SET_RANDOM_ADDRESS]
    assert len(set_addr) >= 2
    addresses = {c.parameters for c in set_addr}
    assert len(addresses) >= 2          # the address actually changed


async def test_stop_rotation_is_idempotent_and_safe_before_start():
    hci = FakeHCI()
    privacy = PrivacyManager(hci=hci)
    await privacy.stop_rotation()       # never started
    await privacy.start_rotation(0.01)
    await privacy.stop_rotation()
    await privacy.stop_rotation()


async def test_set_random_address_disables_resolution_first():
    """The controller answers Command Disallowed (0x0C) to
    LE_Set_Random_Address while address resolution is enabled — so resolution
    must be turned off around the write (and restored). Without this a second
    programming (next test case, or the TGAP rotation) silently fails and the
    IUT keeps advertising from the previous address."""
    from pybluehost.hci.constants import HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE

    hci = FakeHCI()
    privacy = PrivacyManager(hci=hci)
    await privacy.set_address_resolution(True)
    hci.commands.clear()

    assert await privacy.set_random_address(bytes.fromhex("6b f5 1b 8d 8d 1a")) is True

    opcodes = [c.opcode for c in hci.commands]
    assert opcodes[0] == HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE
    assert hci.commands[0].parameters == b"\x00"        # disabled first
    assert HCI_LE_SET_RANDOM_ADDRESS in opcodes
    assert opcodes[-1] == HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE
    assert hci.commands[-1].parameters == b"\x01"        # restored


async def test_rotation_pauses_advertising_around_the_swap():
    """LE_Set_Random_Address is Command Disallowed while advertising is on, so
    rotation must stop advertising first and restart it afterwards with the
    same parameters (BCST/BV-04 watches the address change on air)."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    privacy = PrivacyManager(hci=hci)
    await advertiser.start(AdvertisingConfig(), ad_data=AdvertisingData())
    privacy.set_rotation_hooks(
        advertiser.pause_for_address_change,
        advertiser.resume_after_address_change,
        advertiser.set_random_address,
    )
    hci.commands.clear()

    await privacy.set_random_address(bytes.fromhex("6b f5 1b 8d 8d 1a"))

    ops = [c.opcode for c in hci.commands]
    assert ops[0] == HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
    assert hci.commands[0].parameters == bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x00])
    assert HCI_LE_SET_RANDOM_ADDRESS in ops
    assert HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS in ops
    assert ops[-1] == HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
    assert hci.commands[-1].parameters == bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00])


async def test_set_random_address_restores_resolution_before_resuming_advertising():
    """Intel answers Command Disallowed (0x0C) to
    LE_Set_Address_Resolution_Enable while an advertising set is enabled. The
    restore therefore has to land inside the advertising-paused window — doing
    it after the resume left resolution off for the rest of the session, so an
    incoming connection from the peer's RPA was reported as the RPA instead of
    its identity and address-keyed commands (GAP/PRIV/CONN/BV-10's disconnect)
    could no longer match."""
    from pybluehost.hci.constants import HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE

    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    privacy = PrivacyManager(hci=hci)
    await advertiser.start(AdvertisingConfig(), ad_data=AdvertisingData())
    privacy.set_rotation_hooks(
        advertiser.pause_for_address_change,
        advertiser.resume_after_address_change,
        advertiser.set_random_address,
    )
    await privacy.set_address_resolution(True)
    hci.commands.clear()

    assert await privacy.set_random_address(bytes.fromhex("6b f5 1b 8d 8d 1a")) is True

    ops = [c.opcode for c in hci.commands]
    resolution_on = [
        i for i, c in enumerate(hci.commands)
        if c.opcode == HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE and c.parameters == b"\x01"
    ]
    resolution_off = [
        i for i, c in enumerate(hci.commands)
        if c.opcode == HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE and c.parameters == b"\x00"
    ]
    resume = [
        i for i, c in enumerate(hci.commands)
        if c.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
        and c.parameters[0] == 0x01
    ]
    assert resolution_on and resolution_off and resume
    # The controller answers Command Disallowed to the resolution toggle in
    # either direction while advertising is enabled, so both toggles must sit
    # inside the paused window.
    assert resolution_on[-1] < resume[-1]
    pause = next(
        i for i, c in enumerate(hci.commands)
        if c.opcode == HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE
        and c.parameters[0] == 0x00
    )
    assert pause < resolution_off[0]
    # The write itself still happens in the paused window, after the pause.
    assert pause < ops.index(HCI_LE_SET_RANDOM_ADDRESS)


async def test_rotation_programs_the_advertising_set_address():
    """The rotating address has to land in the advertising set too, or the set
    keeps advertising with the previous one (BCST/BV-04)."""
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    privacy = PrivacyManager(hci=hci)
    privacy.set_rotation_hooks(
        advertiser.pause_for_address_change,
        advertiser.resume_after_address_change,
        advertiser.set_random_address,
    )
    hci.commands.clear()
    address = bytes.fromhex("6b f5 1b 8d 8d 1a")

    await privacy.set_random_address(address)

    set_addr = next(
        c for c in hci.commands if c.opcode == HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS
    )
    assert set_addr.parameters == bytes([0x00]) + address


async def test_set_random_address_while_not_advertising_skips_pause():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    privacy = PrivacyManager(hci=hci)
    privacy.set_rotation_hooks(
        advertiser.pause_for_address_change,
        advertiser.resume_after_address_change,
    )

    assert await privacy.set_random_address(bytes(6)) is True
    assert [c.opcode for c in hci.commands] == [HCI_LE_SET_RANDOM_ADDRESS]


def test_smp_local_irk_is_stable_and_16_bytes():
    """The IRK distributed to the peer during pairing must be the same key the
    privacy manager builds RPAs from — otherwise the peer cannot resolve us."""
    from pybluehost.ble.smp import SMPManager

    smp = SMPManager()
    first = smp.local_irk
    assert len(first) == 16
    assert smp.local_irk == first        # stable across reads


def test_privacy_rpa_uses_the_smp_irk():
    """An RPA generated with the stack IRK resolves against that same IRK."""
    from pybluehost.ble.smp import SMPManager

    smp = SMPManager()
    rpa = PrivacyManager.generate_rpa(smp.local_irk)
    assert PrivacyManager.resolve_rpa(rpa, smp.local_irk) is True


def test_set_local_irk_pins_the_identity_used_for_rpas():
    """The PTS IUT pins its IRK to the value it publishes as the
    TSPX_iut_device_IRK PIXIT, so the Lower Tester can resolve our RPAs."""
    from pybluehost.ble.smp import SMPManager

    smp = SMPManager()
    pinned = bytes.fromhex("00112233445566778899aabbccddeeff")
    smp.set_local_irk(pinned)
    assert smp.local_irk == pinned

    rpa = PrivacyManager.generate_rpa(smp.local_irk)
    assert PrivacyManager.resolve_rpa(rpa, pinned) is True


def test_ah_pads_the_prand_most_significant_octet_first():
    """Core Vol 3 Part H §2.2.2: r' = padding || r, e.g. the 24-bit value
    0x423456 becomes 0x00000000000000000000000000423456 — i.e. r is handed to
    aes128 most-significant-octet first (r[0] ends up adjacent to the zero
    padding, at byte 13)."""
    from pybluehost.ble.smp import SMPCrypto, _aes_ecb

    k = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    r = bytes.fromhex("423456")          # value 0x423456, MSB first
    expected = _aes_ecb(k, bytes(13) + bytes.fromhex("423456"))
    assert SMPCrypto.ah(k, r) == expected[13:16]


def test_rpa_wire_order_matches_ah_convention():
    """The on-air RPA is    [hash_lsb,hash_mid,hash_msb, prand_lsb,prand_mid,prand_msb]
    while ah() works on the 24-bit *values* MSB-first. Pin both directions so a
    regression in either reversal is caught."""
    from pybluehost.ble.smp import SMPCrypto

    irk = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    # Construct a wire prand whose 24-bit value is 0x423456.
    wire_prand = bytes.fromhex("563442")
    value = wire_prand[::-1]
    hash_value = SMPCrypto.ah(irk, value)                 # MSB-first
    wire_rpa = bytes(hash_value[::-1]) + wire_prand       # on-air order

    assert PrivacyManager.resolve_rpa(wire_rpa, irk) is True
    assert PrivacyManager.resolve_rpa(wire_rpa, bytes(16)) is False


def test_generate_rpa_puts_the_resolvable_bits_in_the_right_octet():
    """prand's two most significant bits must be 01; on air that octet is the
    LAST address byte (byte 5)."""
    irk = bytes(16)
    for _ in range(20):
        rpa = PrivacyManager.generate_rpa(irk, random_bytes=bytes.fromhex("010203"))
        assert rpa[5] & 0xC0 == 0x40
        assert PrivacyManager.resolve_rpa(rpa, irk) is True


async def test_set_sync_transfer_parameters_includes_the_connection_handle():
    """LE_Set_Periodic_Advertising_Sync_Transfer_Parameters is
    ``Connection_Handle(2) + Mode(1) + Skip(2) + Sync_Timeout(2) + CTE_Type(1)``
    (Vol 4 Part E §7.8.91). Packing it without the handle sends six octets and
    the controller rejects the command, so a Lower Tester's Periodic Advertising
    Sync Transfer never reaches us and every PAST case dies waiting for it
    (GAP/PADV/PASE/BV-03…, GAP/PADV/PAST/*)."""
    import struct

    from pybluehost.hci.constants import (
        HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS,
    )

    hci = FakeHCI()
    padv = PeriodicAdvertising(hci=hci)

    await padv.set_sync_transfer_parameters(
        conn_handle=0x0042, mode=0x02, skip=0x0003, sync_timeout=0x01F4)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS
    assert cmd.parameters == struct.pack("<HBHHB", 0x0042, 0x02, 0x0003, 0x01F4, 0)
    assert len(cmd.parameters) == 8


async def test_scanner_uses_the_configured_own_address_type():
    """LE_Set_Extended_Scan_Parameters Own_Address_Type must be honoured.

    GAP/BROB/OBSV/BV-05/06 have the IUT observe with a non-resolvable or
    resolvable private address. It was hardcoded 0x00 (public), so the
    controller scanned from the public address and PTS never saw the private
    one no matter how many times the case ran.
    """
    hci = FakeHCI()
    scanner = BLEScanner(hci=hci)

    await scanner.start(ScanConfig(active=True, own_address_type=0x01))

    cmd = next(c for c in hci.commands
               if c.opcode == HCI_LE_SET_EXTENDED_SCAN_PARAMS)
    own_addr_type, filter_policy, phys, scan_type = cmd.parameters[:4]
    assert own_addr_type == 0x01      # random / private
    assert filter_policy == 0x00
    assert phys == 0x01               # LE 1M; the BE200 refuses the Coded bit
    assert scan_type == 0x01          # active
