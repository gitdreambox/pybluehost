"""Tests for built-in BLE profile servers."""
from __future__ import annotations

import struct

from pybluehost.ble.gatt import GATTServer
from pybluehost.core.uuid import UUID16


# ---------------------------------------------------------------------------
# GAP Service
# ---------------------------------------------------------------------------

async def test_gap_service_register_and_read_name():
    from pybluehost.profiles.ble.gap_service import GAPServiceServer

    server = GAPServiceServer(device_name="TestDevice")
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A00))
    assert handle is not None
    assert gatt.db.read(handle) == b"TestDevice"


async def test_gap_service_read_appearance():
    from pybluehost.profiles.ble.gap_service import GAPServiceServer

    server = GAPServiceServer(appearance=0x0080)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A01))
    assert handle is not None
    assert struct.unpack("<H", gatt.db.read(handle))[0] == 0x0080


# ---------------------------------------------------------------------------
# GATT Service
# ---------------------------------------------------------------------------

async def test_gatt_service_register():
    from pybluehost.profiles.ble.gatt_service import GATTServiceServer

    server = GATTServiceServer()
    gatt = GATTServer()
    await server.register(gatt)
    # Service Changed is indicate-only, no read value stored
    assert len(gatt.db._attrs) > 0


# ---------------------------------------------------------------------------
# DIS
# ---------------------------------------------------------------------------

async def test_dis_register_and_read_manufacturer():
    from pybluehost.profiles.ble.dis import DeviceInformationServer

    server = DeviceInformationServer(manufacturer="ACME", model="X1")
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A29))
    assert handle is not None
    assert gatt.db.read(handle) == b"ACME"


async def test_dis_register_and_read_model():
    from pybluehost.profiles.ble.dis import DeviceInformationServer

    server = DeviceInformationServer(manufacturer="ACME", model="X1")
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A24))
    assert handle is not None
    assert gatt.db.read(handle) == b"X1"


# ---------------------------------------------------------------------------
# BAS
# ---------------------------------------------------------------------------

async def test_bas_register_and_read_level():
    from pybluehost.profiles.ble.bas import BatteryServer

    server = BatteryServer(initial_level=85)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A19))
    assert handle is not None
    assert gatt.db.read(handle) == bytes([85])


async def test_bas_update_level():
    from pybluehost.profiles.ble.bas import BatteryServer

    server = BatteryServer(initial_level=100)
    await server.update_level(50)
    data = await server.read_level()
    assert data == bytes([50])


async def test_bas_update_level_refreshes_gatt_value_and_notifies():
    from pybluehost.profiles.ble.bas import BatteryServer

    server = BatteryServer(initial_level=50)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A19))
    assert handle is not None
    notifications = []
    gatt.on_notification_sent(lambda h, value, conn: notifications.append((h, value, conn)))
    gatt.enable_notifications(conn_handle=0x0040, value_handle=handle)

    await server.update_level(73)

    assert gatt.db.read(handle) == bytes([73])
    assert notifications == [(handle, bytes([73]), 0x0040)]


# ---------------------------------------------------------------------------
# HRS
# ---------------------------------------------------------------------------

async def test_hrs_register_and_read_location():
    from pybluehost.profiles.ble.hrs import HeartRateServer

    server = HeartRateServer(sensor_location=0x01)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A38))
    assert handle is not None
    assert gatt.db.read(handle) == bytes([0x01])


async def test_hrs_update_measurement():
    from pybluehost.profiles.ble.hrs import HeartRateServer

    server = HeartRateServer()
    await server.update_measurement(72)
    data = await server.notify_hrm()
    assert data == bytes([0x00, 72])


async def test_hrs_update_measurement_refreshes_gatt_value_and_notifies():
    from pybluehost.profiles.ble.hrs import HeartRateServer

    server = HeartRateServer()
    server._energy_expended = 10
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A37))
    assert handle is not None
    notifications = []
    gatt.on_notification_sent(lambda h, value, conn: notifications.append((h, value, conn)))
    gatt.enable_notifications(conn_handle=0x0041, value_handle=handle)

    await server.update_measurement(91)

    assert gatt.db.read(handle) == bytes([0x00, 91])
    assert notifications == [(handle, bytes([0x00, 91]), 0x0041)]


async def test_hrs_write_control_point_is_bound_to_att_request():
    from pybluehost.ble.att import ATT_Write_Request, ATT_Write_Response
    from pybluehost.profiles.ble.hrs import HeartRateServer

    server = HeartRateServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A39))
    assert handle is not None

    response = await gatt.handle_request(
        conn_handle=0x0041,
        pdu=ATT_Write_Request(attribute_handle=handle, attribute_value=b"\x01"),
    )

    assert isinstance(response, ATT_Write_Response)
    assert server._energy_expended == 0


# ---------------------------------------------------------------------------
# BLS
# ---------------------------------------------------------------------------

async def test_bls_register_and_read_feature():
    from pybluehost.profiles.ble.bls import BloodPressureServer

    server = BloodPressureServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A49))
    assert handle is not None
    assert struct.unpack("<H", gatt.db.read(handle))[0] == 0x0000


# ---------------------------------------------------------------------------
# HIDS
# ---------------------------------------------------------------------------

async def test_hids_register_and_read_report_map():
    from pybluehost.profiles.ble.hids import HIDServer

    report_map = bytes.fromhex("05010902")
    server = HIDServer(report_map=report_map)
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A4B))
    assert handle is not None
    assert gatt.db.read(handle) == report_map


async def test_hids_register_and_read_info():
    from pybluehost.profiles.ble.hids import HIDServer

    server = HIDServer(hid_info=bytes([0x11, 0x01, 0x00, 0x03]))
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A4A))
    assert handle is not None
    assert gatt.db.read(handle) == bytes([0x11, 0x01, 0x00, 0x03])


# ---------------------------------------------------------------------------
# RSCS
# ---------------------------------------------------------------------------

async def test_rscs_register():
    from pybluehost.profiles.ble.rscs import RSCServer

    server = RSCServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A54))
    assert handle is not None
    assert gatt.db.read(handle) == bytes([0x00, 0x00])


# ---------------------------------------------------------------------------
# CSCS
# ---------------------------------------------------------------------------

async def test_cscs_register():
    from pybluehost.profiles.ble.cscs import CSCServer

    server = CSCServer()
    gatt = GATTServer()
    await server.register(gatt)
    handle = gatt.find_characteristic_value_handle(UUID16(0x2A5C))
    assert handle is not None
    assert gatt.db.read(handle) == bytes([0x00, 0x00])
