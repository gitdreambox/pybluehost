"""Tests for Stack, StackConfig, StackMode."""
from __future__ import annotations

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
from pybluehost.hci.constants import ErrorCode, LEMetaSubEvent
from pybluehost.hci.packets import (
    HCIACLData,
    HCI_Connection_Complete_Event,
    HCI_Disconnection_Complete_Event,
    HCI_LE_Meta_Event,
)
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
            b"\x11\x22\x33\x44\x55\x66"
            + bytes([len(raw_ad)])
            + raw_ad
            + bytes([0xD6])
        ),
    )

    raw_event = bytes([0x04, 0x3E, 1 + len(event.subevent_parameters), event.subevent_code])
    raw_event += event.subevent_parameters

    await stack.hci.on_transport_data(raw_event)

    assert len(results) == 1
    assert str(results[0].address) == "11:22:33:44:55:66"
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
