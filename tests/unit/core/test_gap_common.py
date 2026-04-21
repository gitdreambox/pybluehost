"""Tests for GAP common types: AdvertisingData, Appearance, ClassOfDevice."""
from __future__ import annotations

from pybluehost.core.gap_common import (
    AdvertisingData,
    Appearance,
    ClassOfDevice,
    DeviceInfo,
    FilterPolicy,
)
from pybluehost.core.address import BDAddress


def test_advertising_data_flags():
    ad = AdvertisingData()
    ad.set_flags(0x06)
    raw = ad.to_bytes()
    assert raw[0] == 2      # length
    assert raw[1] == 0x01   # AD type: Flags
    assert raw[2] == 0x06


def test_advertising_data_complete_name():
    ad = AdvertisingData()
    ad.set_complete_local_name("PyBH")
    raw = ad.to_bytes()
    assert 0x09 in raw
    idx = raw.index(0x09)
    assert raw[idx + 1:idx + 5] == b"PyBH"


def test_advertising_data_uuid16():
    ad = AdvertisingData()
    ad.add_service_uuid16(0x180D)
    raw = ad.to_bytes()
    assert 0x03 in raw
    assert b"\x0D\x18" in raw


def test_advertising_data_manufacturer():
    ad = AdvertisingData()
    ad.set_manufacturer_specific(company_id=0x0006, data=b"\xAB\xCD")
    raw = ad.to_bytes()
    assert 0xFF in raw


def test_advertising_data_from_bytes_roundtrip():
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Test")
    raw = ad.to_bytes()
    decoded = AdvertisingData.from_bytes(raw)
    assert decoded.get_complete_local_name() == "Test"


def test_advertising_data_tx_power():
    ad = AdvertisingData()
    ad.set_tx_power(-10)
    raw = ad.to_bytes()
    assert 0x0A in raw  # AD type: TX Power Level


def test_advertising_data_multiple_fields():
    ad = AdvertisingData()
    ad.set_flags(0x06)
    ad.set_complete_local_name("Dev")
    ad.add_service_uuid16(0x180F)
    raw = ad.to_bytes()
    decoded = AdvertisingData.from_bytes(raw)
    assert decoded.get_flags() == 0x06
    assert decoded.get_complete_local_name() == "Dev"


def test_appearance_enum():
    assert Appearance.GENERIC_PHONE == 0x0040
    assert Appearance.HEART_RATE_SENSOR == 0x0341


def test_class_of_device():
    cod = ClassOfDevice(major_device_class=0x01, minor_device_class=0x04, service_class=0x200)
    val = cod.to_int()
    assert val == (0x200 << 13) | (0x01 << 8) | (0x04 << 2)


def test_class_of_device_from_int():
    original = ClassOfDevice(major_device_class=0x02, minor_device_class=0x05, service_class=0x100)
    val = original.to_int()
    restored = ClassOfDevice.from_int(val)
    assert restored.major_device_class == 0x02
    assert restored.minor_device_class == 0x05
    assert restored.service_class == 0x100


def test_filter_policy_values():
    assert FilterPolicy.ACCEPT_ALL == 0x00
    assert FilterPolicy.WHITE_LIST_ONLY == 0x01


def test_device_info():
    addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    info = DeviceInfo(address=addr, rssi=-65, name="TestDev")
    assert info.address == addr
    assert info.rssi == -65
    assert info.name == "TestDev"
