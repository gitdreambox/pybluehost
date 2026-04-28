"""Tests for Classic GAP: Discovery, Discoverability, ConnectionManager, SSP."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.classic.gap import (
    ClassicConnection,
    ClassicConnectionManager,
    ClassicDiscoverability,
    ClassicDiscovery,
    InquiryConfig,
    SSPManager,
    SSPMethod,
    ScanEnableFlags,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.gap_common import ClassOfDevice
from pybluehost.hci.constants import (
    EventCode,
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_REMOTE_NAME_REQUEST,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_WRITE_CLASS_OF_DEVICE,
    HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_SCAN_ENABLE,
    ErrorCode,
)
from pybluehost.hci.packets import HCI_Command_Complete_Event, HCIEvent


class FakeHCI:
    def __init__(self) -> None:
        self.commands: list = []

    async def send_command(self, cmd: object) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )


class BlockingHCI(FakeHCI):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def send_command(self, cmd: object) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        await self.release.wait()
        return HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=cmd.opcode,
            return_parameters=bytes([ErrorCode.SUCCESS]),
        )


# ---------------------------------------------------------------------------
# ClassicDiscovery
# ---------------------------------------------------------------------------

async def test_discovery_start_sends_inquiry():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    await disc.start()
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_INQUIRY in opcodes


async def test_discovery_stop_sends_cancel():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    await disc.start()
    hci.commands.clear()
    await disc.stop()
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_INQUIRY_CANCEL in opcodes


async def test_discovery_remote_name_request():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await disc.request_remote_name(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_REMOTE_NAME_REQUEST in opcodes


async def test_discovery_on_result_handler():
    from pybluehost.core.gap_common import DeviceInfo

    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    results: list[DeviceInfo] = []
    disc.on_result(lambda r: results.append(r))
    info = DeviceInfo(address=BDAddress.from_string("11:22:33:44:55:66"), rssi=-50)
    await disc._on_inquiry_result(info)
    assert len(results) == 1
    assert results[0].rssi == -50


async def test_discovery_parses_inquiry_result_event():
    hci = FakeHCI()
    disc = ClassicDiscovery(hci=hci)
    results = []
    disc.on_result(lambda r: results.append(r))
    event = HCIEvent(
        event_code=EventCode.INQUIRY_RESULT,
        parameters=(
            b"\x01"  # Num responses
            b"\x11\x22\x33\x44\x55\x66"  # BD_ADDR
            b"\x01"  # Page scan repetition mode
            b"\x00"  # Reserved
            b"\x04\x02\x0C"  # Class of device
            b"\x00\x00"  # Clock offset
        ),
    )

    await disc.on_hci_event(event)

    assert len(results) == 1
    assert str(results[0].address) == "11:22:33:44:55:66"
    assert results[0].class_of_device == 0x0C0204


# ---------------------------------------------------------------------------
# ClassicDiscoverability
# ---------------------------------------------------------------------------

async def test_set_discoverable():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_discoverable(True)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_SCAN_ENABLE in opcodes
    # Check scan enable byte includes inquiry scan bit
    cmd = hci.commands[-1]
    assert cmd.parameters[0] & ScanEnableFlags.INQUIRY_SCAN_ONLY


async def test_set_connectable():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_connectable(True)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_SCAN_ENABLE in opcodes
    cmd = hci.commands[-1]
    assert cmd.parameters[0] & ScanEnableFlags.PAGE_SCAN_ONLY


async def test_set_device_name():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_device_name("PyBH-Device")
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_LOCAL_NAME in opcodes
    cmd = hci.commands[-1]
    assert cmd.parameters[:11] == b"PyBH-Device"
    assert len(cmd.parameters) == 248


async def test_set_class_of_device():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    cod = ClassOfDevice(major_device_class=0x01, minor_device_class=0x04)
    await d.set_class_of_device(cod)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_CLASS_OF_DEVICE in opcodes


async def test_set_eir():
    hci = FakeHCI()
    d = ClassicDiscoverability(hci=hci)
    await d.set_extended_inquiry_response(b"\x02\x01\x06")
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_WRITE_EXTENDED_INQUIRY_RESPONSE in opcodes
    cmd = hci.commands[-1]
    assert len(cmd.parameters) == 241  # 1 (FEC) + 240 (EIR data)


# ---------------------------------------------------------------------------
# ClassicConnectionManager
# ---------------------------------------------------------------------------

async def test_classic_connect():
    hci = FakeHCI()
    mgr = ClassicConnectionManager(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await mgr.connect(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_CREATE_CONNECTION in opcodes


async def test_classic_connect_packs_bd_addr_little_endian_on_wire():
    hci = FakeHCI()
    mgr = ClassicConnectionManager(hci=hci)
    addr = BDAddress.from_string("1A:8D:8D:1B:F5:6B")

    await mgr.connect(addr)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_CREATE_CONNECTION
    assert cmd.parameters[:6] == bytes.fromhex("6b f5 1b 8d 8d 1a")


async def test_classic_accept():
    hci = FakeHCI()
    mgr = ClassicConnectionManager(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await mgr.accept(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_ACCEPT_CONNECTION_REQ in opcodes


async def test_classic_authenticate_sends_auth_requested():
    hci = FakeHCI()
    mgr = ClassicConnectionManager(hci=hci)

    await mgr.authenticate(0x0048)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_AUTH_REQUESTED
    assert cmd.parameters == b"\x48\x00"


async def test_classic_set_encryption_sends_set_connection_encryption():
    hci = FakeHCI()
    mgr = ClassicConnectionManager(hci=hci)

    await mgr.set_encryption(0x0048, enabled=True)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_SET_CONNECTION_ENCRYPTION
    assert cmd.parameters == b"\x48\x00\x01"


def test_classic_connection_dataclass():
    conn = ClassicConnection(
        handle=0x0041,
        peer_address=BDAddress.from_string("AA:BB:CC:DD:EE:FF"),
    )
    assert conn.handle == 0x0041
    assert conn.encrypted is False


# ---------------------------------------------------------------------------
# SSPManager
# ---------------------------------------------------------------------------

async def test_ssp_io_capability_reply():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    ssp.set_io_capability(0x01)  # DisplayYesNo
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await ssp.reply_io_capability(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_IO_CAPABILITY_REQUEST_REPLY in opcodes
    # Verify IO cap byte in params
    cmd = hci.commands[-1]
    assert cmd.parameters[6] == 0x01  # after 6-byte address
    assert cmd.parameters[8] == 0x00  # no MITM requirement by default


async def test_ssp_on_io_capability_request_replies():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    ssp.set_io_capability(0x03)
    event = HCIEvent(
        event_code=EventCode.IO_CAPABILITY_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a"),
    )

    await ssp.on_hci_event(event)
    await asyncio.sleep(0)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_IO_CAPABILITY_REQUEST_REPLY
    assert cmd.parameters[:6] == bytes.fromhex("6b f5 1b 8d 8d 1a")
    assert cmd.parameters[6] == 0x03


async def test_ssp_on_io_capability_request_does_not_wait_for_command_status():
    hci = BlockingHCI()
    ssp = SSPManager(hci=hci)
    event = HCIEvent(
        event_code=EventCode.IO_CAPABILITY_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a"),
    )

    await asyncio.wait_for(ssp.on_hci_event(event), timeout=0.05)
    await asyncio.sleep(0)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_IO_CAPABILITY_REQUEST_REPLY
    hci.release.set()
    await asyncio.sleep(0)


async def test_ssp_on_user_confirmation_request_accepts_by_default():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    event = HCIEvent(
        event_code=EventCode.USER_CONFIRMATION_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a") + (963370).to_bytes(4, "little"),
    )

    await ssp.on_hci_event(event)
    await asyncio.sleep(0)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_USER_CONFIRMATION_REQUEST_REPLY
    assert cmd.parameters == bytes.fromhex("6b f5 1b 8d 8d 1a")


async def test_ssp_on_user_confirmation_request_can_deny():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    ssp.on_user_confirmation(lambda _address, _numeric_value: False)
    event = HCIEvent(
        event_code=EventCode.USER_CONFIRMATION_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a") + (963370).to_bytes(4, "little"),
    )

    await ssp.on_hci_event(event)
    await asyncio.sleep(0)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY
    assert cmd.parameters == bytes.fromhex("6b f5 1b 8d 8d 1a")


async def test_ssp_on_link_key_request_replies_negative():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    event = HCIEvent(
        event_code=EventCode.LINK_KEY_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a"),
    )

    await ssp.on_hci_event(event)
    await asyncio.sleep(0)

    cmd = hci.commands[-1]
    assert cmd.opcode == HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY
    assert cmd.parameters == bytes.fromhex("6b f5 1b 8d 8d 1a")


async def test_ssp_confirm():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await ssp.confirm(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_USER_CONFIRMATION_REQUEST_REPLY in opcodes


async def test_ssp_deny():
    hci = FakeHCI()
    ssp = SSPManager(hci=hci)
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    await ssp.deny(addr)
    opcodes = [c.opcode for c in hci.commands]
    assert HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY in opcodes


def test_ssp_method_enum():
    assert SSPMethod.JUST_WORKS == 0
    assert SSPMethod.NUMERIC_COMPARISON == 1
    assert SSPMethod.PASSKEY_ENTRY == 2
    assert SSPMethod.OOB == 3


# ---------------------------------------------------------------------------
# ScanEnableFlags
# ---------------------------------------------------------------------------

def test_scan_enable_flags():
    assert ScanEnableFlags.NO_SCANS == 0x00
    assert ScanEnableFlags.INQUIRY_AND_PAGE_SCAN == 0x03


# ---------------------------------------------------------------------------
# Unified GAP
# ---------------------------------------------------------------------------

def test_unified_gap_construction():
    from pybluehost.gap import GAP

    gap = GAP()
    assert gap.ble_advertiser is None
    assert gap.classic_discovery is None
    assert gap.pairing_delegate is None


def test_unified_gap_with_subsystems():
    from pybluehost.gap import GAP

    hci = FakeHCI()
    adv = __import__("pybluehost.ble.gap", fromlist=["BLEAdvertiser"]).BLEAdvertiser(hci)
    disc = ClassicDiscovery(hci=hci)
    gap = GAP(ble_advertiser=adv, classic_discovery=disc)
    assert gap.ble_advertiser is adv
    assert gap.classic_discovery is disc


def test_unified_gap_set_pairing_delegate():
    from pybluehost.gap import GAP

    gap = GAP()

    class MyDelegate:
        pass

    delegate = MyDelegate()
    gap.set_pairing_delegate(delegate)
    assert gap.pairing_delegate is delegate
