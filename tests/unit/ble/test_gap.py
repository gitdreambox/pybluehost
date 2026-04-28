"""Tests for BLE GAP: Advertiser, Scanner, ConnectionManager, WhiteList, ExtendedAdvertiser."""
from __future__ import annotations

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
    PrivacyManager,
    ScanConfig,
    ScanResult,
    WhiteList,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import (
    HCI_LE_ADD_DEVICE_TO_WHITE_LIST,
    HCI_LE_CLEAR_WHITE_LIST,
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE,
    HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_Command_Complete_Event, HCI_LE_Meta_Event
from pybluehost.hci.constants import ErrorCode


class FakeHCI:
    """Minimal HCI mock that records commands and returns success."""

    def __init__(self) -> None:
        self.commands: list = []

    async def send_command(self, cmd: object) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )


# ---------------------------------------------------------------------------
# BLEAdvertiser
# ---------------------------------------------------------------------------

async def test_advertiser_start_sends_hci_commands():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Test")
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    opcodes = [cmd.opcode for cmd in hci.commands]
    assert HCI_LE_SET_ADVERTISING_PARAMS in opcodes
    assert HCI_LE_SET_ADVERTISING_DATA in opcodes
    assert HCI_LE_SET_ADVERTISE_ENABLE in opcodes


async def test_advertiser_stop():
    hci = FakeHCI()
    advertiser = BLEAdvertiser(hci=hci)
    ad = AdvertisingData()
    await advertiser.start(config=AdvertisingConfig(), ad_data=ad)
    hci.commands.clear()
    await advertiser.stop()
    opcodes = [cmd.opcode for cmd in hci.commands]
    assert HCI_LE_SET_ADVERTISE_ENABLE in opcodes


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
            b"\x11\x22\x33\x44\x55\x66"
            + bytes([len(raw_ad)])
            + raw_ad
            + bytes([0xD6])  # -42 dBm
        ),
    )

    await scanner.on_hci_event(event)

    assert len(results) == 1
    assert str(results[0].address) == "11:22:33:44:55:66"
    assert results[0].rssi == -42
    assert results[0].local_name == "PBH"


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
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await wl.add(addr, address_type=0x00)
    assert HCI_LE_ADD_DEVICE_TO_WHITE_LIST in [cmd.opcode for cmd in hci.commands]


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
    from pybluehost.ble.smp import SMPCrypto
    # ah(k, r) test: if we have IRK and prand, we can verify the hash
    irk = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    prand = bytes.fromhex("708194")
    expected_hash = SMPCrypto.ah(irk, prand)
    # Build an RPA: hash(3) || prand(3)
    rpa_bytes = expected_hash + prand
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
