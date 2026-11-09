"""Tests for Stack, StackConfig, StackMode."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.ble.att import ATT_Read_Request, ATT_Write_Request, ATTOpcode
from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    GATTClient,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.core.types import IOCapability
from pybluehost.core.uuid import UUID16
from pybluehost.hci.constants import ErrorCode, EventCode, LEMetaSubEvent
from pybluehost.hci.packets import (
    HCIACLData,
    HCI_Connection_Complete_Event,
    HCI_Disconnection_Complete_Event,
    HCIEvent,
    HCI_LE_Meta_Event,
)
from pybluehost.l2cap.constants import PSM_SDP
from pybluehost.stack import Stack, StackConfig, StackMode


# ---------------------------------------------------------------------------
# StackConfig + StackMode
# ---------------------------------------------------------------------------

def test_default_config():
    config = StackConfig()
    assert config.device_name == "PyBlueHost"
    assert config.command_timeout == 5.0
    assert config.le_io_capability == IOCapability.NO_INPUT_NO_OUTPUT
    assert config.classic_io_capability == IOCapability.DISPLAY_YES_NO
    assert config.appearance == 0x0000
    assert config.trace_sinks == []


def test_custom_config():
    config = StackConfig(device_name="MyDevice", command_timeout=10.0)
    assert config.device_name == "MyDevice"
    assert config.command_timeout == 10.0


def test_stack_mode_enum():
    assert StackMode.LIVE == "live"
    assert StackMode.VIRTUAL == "virtual"
    assert StackMode.REPLAY == "replay"


def test_stack_config_security_field():
    from pybluehost.ble.security import SecurityConfig

    config = StackConfig()
    assert isinstance(config.security, SecurityConfig)


# ---------------------------------------------------------------------------
# Stack lifecycle (virtual)
# ---------------------------------------------------------------------------

async def test_stack_virtual_creates_powered_stack():
    stack = await Stack.virtual()
    assert stack.is_powered
    assert stack.mode == StackMode.VIRTUAL
    await stack.close()


async def test_stack_virtual_has_local_address():
    stack = await Stack.virtual()
    assert stack.local_address is not None
    await stack.close()


async def test_stack_power_off_on():
    stack = await Stack.virtual()
    assert stack.is_powered
    await stack.power_off()
    assert not stack.is_powered
    await stack.power_on()
    assert stack.is_powered
    await stack.close()


async def test_stack_context_manager():
    async with await Stack.virtual() as stack:
        assert stack.is_powered
    assert not stack.is_powered


async def test_stack_exposes_layers():
    stack = await Stack.virtual()
    assert stack.hci is not None
    assert stack.l2cap is not None
    assert stack.gap is not None
    assert stack.gatt_server is not None
    assert stack.trace is not None
    assert stack.sdp is not None
    assert stack.rfcomm is not None
    await stack.close()


async def test_stack_gap_has_subsystems():
    stack = await Stack.virtual()
    assert stack.gap.ble_advertiser is not None
    assert stack.gap.ble_scanner is not None
    assert stack.gap.ble_connections is not None
    assert stack.gap.classic_discovery is not None
    assert stack.gap.classic_ssp is not None
    assert stack.gap.whitelist is not None
    await stack.close()


async def test_stack_applies_classic_io_capability_to_ssp_manager():
    stack = await Stack.virtual(
        config=StackConfig(classic_io_capability=IOCapability.DISPLAY_YES_NO)
    )
    try:
        assert stack.gap.classic_ssp._io_capability == IOCapability.DISPLAY_YES_NO
    finally:
        await stack.close()


async def test_stack_registers_default_classic_sdp_listener():
    stack = await Stack.virtual()

    assert PSM_SDP in stack.l2cap._classic_listeners

    await stack.close()


async def test_stack_routes_hci_le_advertising_report_to_ble_scanner():
    stack = await Stack.virtual()
    results = []
    stack.gap.ble_scanner.on_result(lambda r: results.append(r))
    ad = AdvertisingData()
    ad.set_complete_local_name("PBH")
    raw_ad = ad.to_bytes()
    event = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_ADVERTISING_REPORT,
        subevent_parameters=(
            b"\x01"
            b"\x00"
            b"\x00"
            b"\x6b\xf5\x1b\x8d\x8d\x1a"
            + bytes([len(raw_ad)])
            + raw_ad
            + bytes([0xD6])
        ),
    )

    raw_event = bytes([0x04, 0x3E, 1 + len(event.subevent_parameters), event.subevent_code])
    raw_event += event.subevent_parameters

    await stack.hci.on_transport_data(raw_event)
    # The scanner holds a report briefly so a scan response can join it into a
    # single EIR (BLEScanner._on_legacy_advertising_report).
    await asyncio.sleep(stack.gap.ble_scanner._MERGE_WINDOW_S + 0.1)

    assert len(results) == 1
    assert str(results[0].address) == "1A:8D:8D:1B:F5:6B"
    await stack.close()


async def test_stack_routes_acl_data_to_l2cap(monkeypatch):
    stack = await Stack.virtual()
    packets = []

    async def on_acl_data(packet):
        packets.append(packet)

    monkeypatch.setattr(stack.l2cap, "on_acl_data", on_acl_data)
    acl = HCIACLData(handle=0x000B, pb_flag=0x02, data=b"\x03\x00\x04\x00att")

    await stack.hci.on_transport_data(acl.to_bytes())

    assert packets == [acl]
    await stack.close()


async def test_stack_routes_att_request_to_gatt_server(monkeypatch):
    stack = await Stack.virtual()
    stack.gatt_server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A38),
                    properties=CharProperties.READ,
                    permissions=Permissions.READABLE,
                    value=b"\x42",
                )
            ],
        )
    )
    sent_acl = []

    async def send_acl_data(handle, pb_flag, data):
        sent_acl.append((handle, pb_flag, data))

    monkeypatch.setattr(stack.hci, "send_acl_data", send_acl_data)
    le_connection_complete = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=b"\x00" + struct.pack("<H", 0x0040) + bytes(16),
    )

    await stack._on_hci_event(le_connection_complete)
    request = ATT_Read_Request(attribute_handle=0x0003).to_bytes()
    acl = HCIACLData(
        handle=0x0040,
        pb_flag=0x02,
        data=struct.pack("<HH", len(request), 0x0004) + request,
    )

    await stack.hci.on_transport_data(acl.to_bytes())

    assert len(sent_acl) == 1
    assert sent_acl[0][0] == 0x0040
    assert sent_acl[0][2] == struct.pack("<HH", 2, 0x0004) + bytes([ATTOpcode.READ_RESPONSE, 0x42])
    await stack.close()


async def test_stack_sends_gatt_notifications_over_att_channel(monkeypatch):
    stack = await Stack.virtual()
    stack.gatt_server.add_service(
        ServiceDefinition(
            uuid=UUID16(0x180D),
            characteristics=[
                CharacteristicDefinition(
                    uuid=UUID16(0x2A37),
                    properties=CharProperties.NOTIFY,
                    permissions=Permissions.READABLE,
                )
            ],
        )
    )
    sent_acl = []

    async def send_acl_data(handle, pb_flag, data):
        sent_acl.append((handle, pb_flag, data))

    monkeypatch.setattr(stack.hci, "send_acl_data", send_acl_data)
    le_connection_complete = HCI_LE_Meta_Event(
        subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
        subevent_parameters=b"\x00" + struct.pack("<H", 0x0040) + bytes(16),
    )
    await stack._on_hci_event(le_connection_complete)

    cccd_write = ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x01\x00").to_bytes()
    acl = HCIACLData(
        handle=0x0040,
        pb_flag=0x02,
        data=struct.pack("<HH", len(cccd_write), 0x0004) + cccd_write,
    )
    await stack.hci.on_transport_data(acl.to_bytes())
    sent_acl.clear()

    await stack.gatt_server.notify(handle=0x0003, value=bytes([0x00, 72]), connections=[0x0040])

    assert len(sent_acl) == 1
    expected_att = bytes([ATTOpcode.HANDLE_VALUE_NOTIFICATION]) + struct.pack("<H", 0x0003) + bytes([0x00, 72])
    assert sent_acl[0][2] == struct.pack("<HH", len(expected_att), 0x0004) + expected_att
    await stack.close()


async def test_stack_connect_gatt_waits_for_le_connection_and_returns_client(monkeypatch):
    stack = await Stack.virtual()

    async def connect(target, config=None):
        event = HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            subevent_parameters=b"\x00" + struct.pack("<H", 0x0041) + bytes(16),
        )
        await stack._on_hci_event(event)

    monkeypatch.setattr(stack.gap.ble_connections, "connect", connect)

    client = await stack.connect_gatt(stack.local_address)

    assert isinstance(client, GATTClient)
    assert stack.l2cap.get_fixed_channel(0x0041, 0x0004) is not None
    await stack.close()


async def test_stack_connect_gatt_reports_le_connection_failure(monkeypatch):
    stack = await Stack.virtual()

    async def connect(target, config=None):
        event = HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            subevent_parameters=bytes([ErrorCode.FAILED_TO_ESTABLISH_CONNECTION])
            + struct.pack("<H", 0x0000)
            + bytes(16),
        )
        await stack._on_hci_event(event)

    monkeypatch.setattr(stack.gap.ble_connections, "connect", connect)

    with pytest.raises(RuntimeError, match="FAILED_TO_ESTABLISH_CONNECTION"):
        await stack.connect_gatt(stack.local_address)

    await stack.close()


async def test_stack_connect_classic_waits_for_acl_connection_and_returns_handle(monkeypatch):
    stack = await Stack.virtual()
    target = stack.local_address

    async def connect(addr, allow_role_switch=True):
        event = HCI_Connection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0042,
            bd_addr=target.address,
            link_type=0x01,
        )
        await stack._on_hci_event(event)

    monkeypatch.setattr(stack.gap.classic_connections, "connect", connect)

    handle = await stack.connect_classic(target)

    assert handle == 0x0042
    assert stack.l2cap.get_fixed_channel(0x0042, 0x0001) is not None
    await stack.close()


async def test_stack_connect_classic_reports_acl_connection_failure(monkeypatch):
    stack = await Stack.virtual()
    target = stack.local_address

    async def connect(addr, allow_role_switch=True):
        event = HCI_Connection_Complete_Event(
            status=ErrorCode.PAGE_TIMEOUT,
            connection_handle=0x0000,
            bd_addr=target.address,
            link_type=0x01,
        )
        await stack._on_hci_event(event)

    monkeypatch.setattr(stack.gap.classic_connections, "connect", connect)

    with pytest.raises(RuntimeError, match="PAGE_TIMEOUT"):
        await stack.connect_classic(target)

    await stack.close()


async def test_stack_authenticate_classic_waits_for_auth_complete(monkeypatch):
    stack = await Stack.virtual()

    async def authenticate(handle):
        assert handle == 0x0048
        await stack._on_hci_event(
            HCIEvent(
                event_code=EventCode.AUTH_COMPLETE,
                parameters=bytes([ErrorCode.SUCCESS]) + struct.pack("<H", handle),
            )
        )

    monkeypatch.setattr(stack.gap.classic_connections, "authenticate", authenticate)

    await stack.authenticate_classic(0x0048)
    await stack.close()


async def test_stack_enable_classic_encryption_waits_for_encryption_change(monkeypatch):
    stack = await Stack.virtual()

    async def set_encryption(handle, enabled=True):
        assert handle == 0x0048
        assert enabled is True
        await stack._on_hci_event(
            HCIEvent(
                event_code=EventCode.ENCRYPTION_CHANGE,
                parameters=bytes([ErrorCode.SUCCESS]) + struct.pack("<H", handle) + b"\x01",
            )
        )

    monkeypatch.setattr(stack.gap.classic_connections, "set_encryption", set_encryption)

    await stack.enable_classic_encryption(0x0048)
    await stack.close()


async def test_stack_reports_disconnection_events():
    stack = await Stack.virtual()
    events = []
    stack.on_connection_event(lambda event: events.append(event))

    await stack._on_hci_event(
        HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0041,
            reason=ErrorCode.FAILED_TO_ESTABLISH_CONNECTION,
        )
    )

    assert events[-1].state == "disconnected"
    assert events[-1].handle == 0x0041
    assert "FAILED_TO_ESTABLISH_CONNECTION" in events[-1].reason
    await stack.close()


async def test_stack_reports_le_connection_peer_address():
    stack = await Stack.virtual()
    events = []
    stack.on_connection_event(lambda event: events.append(event))

    await stack._on_hci_event(
        HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            subevent_parameters=(
                b"\x00"
                + struct.pack("<H", 0x0045)
                + b"\x01"  # peripheral role
                + b"\x00"  # public peer address
                + bytes.fromhex("20e8a56b6f38")
                + bytes(8)
            ),
        )
    )

    assert events[-1].state == "connected"
    assert events[-1].handle == 0x0045
    assert str(events[-1].peer_address) == "38:6F:6B:A5:E8:20"
    assert events[-1].peer_address.type.name == "PUBLIC"
    await stack.close()


async def test_stack_reports_disconnection_peer_address():
    """The "disconnected" event must carry the peer address so listeners can
    identify which peer went away. auto-pts's wait_for_disconnection() matches by
    address — pts-tester drops DEVICE_DISCONNECTED (and PTS then waits ~30 s per
    case) when the disconnect event has no peer_address."""
    stack = await Stack.virtual()
    events = []
    stack.on_connection_event(lambda event: events.append(event))

    # Connect (LE Connection Complete) then disconnect the same handle.
    await stack._on_hci_event(
        HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            subevent_parameters=(
                b"\x00"
                + struct.pack("<H", 0x0045)
                + b"\x01"  # peripheral role
                + b"\x00"  # public peer address
                + bytes.fromhex("20e8a56b6f38")
                + bytes(8)
            ),
        )
    )
    await stack._on_hci_event(
        HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0045,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        )
    )

    disc = events[-1]
    assert disc.state == "disconnected"
    assert disc.handle == 0x0045
    assert disc.peer_address is not None
    assert str(disc.peer_address) == "38:6F:6B:A5:E8:20"
    # The handle is removed from the live map once torn down.
    assert 0x0045 not in stack._le_peer_addrs
    await stack.close()


async def _virtual_stack_with_notify_char():
    """A virtual stack whose GATT server hosts one NOTIFY characteristic
    (value handle 0x0003, auto-added CCCD 0x0004)."""
    stack = await Stack.virtual()
    stack._gatt_server.add_service(ServiceDefinition(
        uuid=UUID16(0xAA40),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0xAA50),
                properties=CharProperties.READ | CharProperties.NOTIFY,
                permissions=Permissions.READABLE, value=b"\x00"),
        ]))
    return stack


async def _connect_le_peer(stack) -> None:
    await stack._on_hci_event(
        HCI_LE_Meta_Event(
            subevent_code=LEMetaSubEvent.LE_CONNECTION_COMPLETE,
            subevent_parameters=(
                b"\x00"
                + struct.pack("<H", 0x0045)
                + b"\x01"  # peripheral role
                + b"\x00"  # public peer address
                + bytes.fromhex("20e8a56b6f38")
                + bytes(8)
            ),
        )
    )


async def _disconnect_le_peer(stack) -> None:
    await stack._on_hci_event(
        HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0045,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        )
    )


async def test_unbonded_disconnect_resets_the_gatt_cccd():
    """GATT.TS GAN/BV-01 step 5A: a non-bonded client's CCCD reads 0x0000 after
    disconnect+reconnect, so the stack must tell the GATT server the LE client
    that just left was not bonded."""
    stack = await _virtual_stack_with_notify_char()
    await _connect_le_peer(stack)
    await stack._gatt_server.handle_request(
        conn_handle=0x0045,
        pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x01\x00"))
    assert stack._gatt_server.db.read(0x0004) == b"\x01\x00"

    await _disconnect_le_peer(stack)
    await asyncio.sleep(0)  # the bond lookup (and reset) runs in a task

    assert stack._gatt_server.db.read(0x0004) == b"\x00\x00"
    await stack.close()


async def test_bonded_disconnect_keeps_the_gatt_cccd():
    """GATT.TS GAN/BV-03 step 5B: a bonded client's CCCD persists across the
    disconnect (0x0001 on reconnect)."""
    from pybluehost.ble.smp import BondInfo, InMemoryBondStorage
    from pybluehost.core.address import BDAddress

    stack = await _virtual_stack_with_notify_char()
    storage = InMemoryBondStorage()
    await storage.save_bond(BondInfo(
        peer_address=BDAddress.from_string("38:6F:6B:A5:E8:20"),
        ltk=b"\x11" * 16))
    stack.config.bond_storage = storage
    await _connect_le_peer(stack)
    await stack._gatt_server.handle_request(
        conn_handle=0x0045,
        pdu=ATT_Write_Request(attribute_handle=0x0004, attribute_value=b"\x01\x00"))

    await _disconnect_le_peer(stack)

    assert stack._gatt_server.db.read(0x0004) == b"\x01\x00"
    await stack.close()


async def test_stack_routes_classic_ssp_events(monkeypatch):
    from pybluehost.hci.constants import EventCode
    from pybluehost.hci.packets import HCIEvent

    stack = await Stack.virtual()
    events = []

    async def on_hci_event(event):
        events.append(event)

    monkeypatch.setattr(stack.gap.classic_ssp, "on_hci_event", on_hci_event)
    event = HCIEvent(
        event_code=EventCode.IO_CAPABILITY_REQUEST,
        parameters=bytes.fromhex("6b f5 1b 8d 8d 1a"),
    )

    await stack._on_hci_event(event)

    assert events == [event]
    await stack.close()


async def test_stack_accepts_incoming_classic_connection_request(monkeypatch):
    stack = await Stack.virtual()
    accepted = []

    async def accept(address, role=0x01):
        accepted.append((address, role))

    monkeypatch.setattr(stack.gap.classic_connections, "accept", accept)
    event = HCIEvent(
        event_code=EventCode.CONNECTION_REQUEST,
        parameters=bytes.fromhex("20 e8 a5 6b 6f 38 0c 42 5a 01"),
    )

    await stack._on_hci_event(event)
    await asyncio.sleep(0)

    assert len(accepted) == 1
    assert str(accepted[0][0]) == "38:6F:6B:A5:E8:20"
    assert accepted[0][1] == 0x01
    await stack.close()


async def test_replay_mode_rejects_connect_gatt():
    from pybluehost.core.address import BDAddress
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()
    stack._l2cap = object()

    with pytest.raises(ReplayModeError):
        await stack.connect_gatt(BDAddress(b"\x01\x02\x03\x04\x05\x06"))


async def test_replay_mode_rejects_connect_classic():
    from pybluehost.core.address import BDAddress
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()
    stack._l2cap = object()

    with pytest.raises(ReplayModeError):
        await stack.connect_classic(BDAddress(b"\x01\x02\x03\x04\x05\x06"))


async def test_stack_config_accepts_bond_storage():
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.stack import StackConfig

    storage = JsonBondStorage(path=":memory:")
    cfg = StackConfig(bond_storage=storage)
    assert cfg.bond_storage is storage


async def test_stack_config_bond_storage_defaults_to_none():
    from pybluehost.stack import StackConfig

    cfg = StackConfig()
    assert cfg.bond_storage is None


async def test_replay_mode_rejects_authenticate_classic():
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()

    with pytest.raises(ReplayModeError):
        await stack.authenticate_classic(handle=0x0040)


async def test_replay_mode_rejects_enable_classic_encryption():
    from pybluehost.core.errors import ReplayModeError
    from pybluehost.stack import Stack, StackMode

    stack = Stack()
    stack._mode = StackMode.REPLAY
    stack._gap = object()

    with pytest.raises(ReplayModeError):
        await stack.enable_classic_encryption(handle=0x0040)


async def test_le_link_local_address_uses_the_advertised_rpa():
    from pybluehost.ble.gap import AdvertisingConfig
    from pybluehost.core.address import AddressType

    stack = await Stack.virtual()
    advertiser = stack.gap.ble_advertiser
    advertiser._random_address = bytes.fromhex("1a5bdb10da70")
    advertiser._last_start = (AdvertisingConfig(own_address_type=0x01), None, None)

    # LE Connection Complete: status, handle, role=Peripheral, then the peer.
    params = (
        bytes([0x00])
        + struct.pack("<H", 0x0800)
        + bytes([0x01, 0x00])
        + bytes.fromhex("eb8dd5539efc")
        + bytes(8)
    )
    addr = stack._le_link_local_address(params)

    assert addr is not None
    assert str(addr) == "70:DA:10:DB:5B:1A"
    assert addr.type == AddressType.RANDOM
    assert addr.to_hci() == bytes.fromhex("1a5bdb10da70")
    await stack.close()


async def test_le_link_local_address_is_none_when_we_advertise_public():
    from pybluehost.ble.gap import AdvertisingConfig

    stack = await Stack.virtual()
    advertiser = stack.gap.ble_advertiser
    advertiser._random_address = bytes.fromhex("1a5bdb10da70")
    advertiser._last_start = (AdvertisingConfig(own_address_type=0x00), None, None)

    params = bytes([0x00]) + struct.pack("<H", 0x0800) + bytes([0x01, 0x00]) + bytes(14)

    assert stack._le_link_local_address(params) is None
    await stack.close()


async def test_le_link_local_address_uses_the_initiator_random_address():
    from pybluehost.core.address import AddressType

    stack = await Stack.virtual()
    stack.gap.ble_connections.initiator_own_address_type = 0x01
    stack.gap.ble_privacy._current_address = bytes.fromhex("1a5bdb10da70")

    # LE Connection Complete: role=Central (we initiated).
    params = bytes([0x00]) + struct.pack("<H", 0x0800) + bytes([0x00, 0x00]) + bytes(14)
    addr = stack._le_link_local_address(params)

    assert addr is not None
    assert str(addr) == "70:DA:10:DB:5B:1A"
    assert addr.type == AddressType.RANDOM
    await stack.close()


async def test_le_link_local_address_ignores_a_public_initiator_address():
    stack = await Stack.virtual()
    stack.gap.ble_connections.initiator_own_address_type = 0x00
    stack.gap.ble_privacy._current_address = bytes.fromhex("1a5bdb10da70")

    params = bytes([0x00]) + struct.pack("<H", 0x0800) + bytes([0x00, 0x00]) + bytes(14)

    assert stack._le_link_local_address(params) is None
    await stack.close()
