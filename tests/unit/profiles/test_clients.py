"""Tests for BLE profile clients (HeartRateClient, BatteryClient, DIS)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pybluehost.core.uuid import UUID16


async def test_heart_rate_client_read_location():
    from pybluehost.profiles.ble.hrs import HeartRateClient

    mock_gatt = MagicMock()
    mock_gatt.discover_all_services = AsyncMock(
        return_value=[MagicMock(uuid=UUID16(0x180D))]
    )
    mock_gatt.discover_characteristics = AsyncMock(
        return_value=[
            MagicMock(uuid=UUID16(0x2A38)),
            MagicMock(uuid=UUID16(0x2A37)),
            MagicMock(uuid=UUID16(0x2A39)),
        ]
    )
    mock_gatt.read_characteristic = AsyncMock(return_value=bytes([0x01]))

    client = HeartRateClient()
    await client.discover(mock_gatt)
    location = await client.read_sensor_location()
    assert location == 0x01


async def test_battery_client_read_level():
    from pybluehost.profiles.ble.bas import BatteryClient

    mock_gatt = MagicMock()
    mock_gatt.discover_all_services = AsyncMock(
        return_value=[MagicMock(uuid=UUID16(0x180F))]
    )
    mock_gatt.discover_characteristics = AsyncMock(
        return_value=[MagicMock(uuid=UUID16(0x2A19))]
    )
    mock_gatt.read_characteristic = AsyncMock(return_value=bytes([85]))

    client = BatteryClient()
    await client.discover(mock_gatt)
    level = await client.read_battery_level()
    assert level == 85


async def test_dis_client_read_manufacturer():
    from pybluehost.profiles.ble.dis import DeviceInformationClient

    mock_gatt = MagicMock()
    mock_gatt.discover_all_services = AsyncMock(
        return_value=[MagicMock(uuid=UUID16(0x180A))]
    )
    mock_gatt.discover_characteristics = AsyncMock(
        return_value=[
            MagicMock(uuid=UUID16(0x2A29)),
            MagicMock(uuid=UUID16(0x2A24)),
        ]
    )
    mock_gatt.read_characteristic = AsyncMock(return_value=b"ACME")

    client = DeviceInformationClient()
    await client.discover(mock_gatt)
    name = await client.read_manufacturer()
    assert name == "ACME"
