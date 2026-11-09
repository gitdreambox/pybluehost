"""Tests for GAP common types: AdvertisingData, Appearance, ClassOfDevice."""
from __future__ import annotations

import pytest

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


def test_advertising_data_service_data16():
    ad = AdvertisingData()
    ad.set_service_data16(0xFE2C, bytes.fromhex("E9161B"))
    raw = ad.to_bytes()
    assert raw == b"\x06\x16\x2C\xFE\xE9\x16\x1B"


# SIG assigned AD types — mirrors pybluehost/lib/sig/assigned_numbers/core/ad_types.yaml.
# Constant name -> assigned value.
_SIG_AD_TYPES = {
    "AD_FLAGS": 0x01,
    "AD_UUID16_MORE": 0x02,
    "AD_UUID16_COMPLETE": 0x03,
    "AD_UUID32_MORE": 0x04,
    "AD_UUID32_COMPLETE": 0x05,
    "AD_UUID128_MORE": 0x06,
    "AD_UUID128_COMPLETE": 0x07,
    "AD_SHORT_LOCAL_NAME": 0x08,
    "AD_COMPLETE_LOCAL_NAME": 0x09,
    "AD_TX_POWER": 0x0A,
    "AD_CLASS_OF_DEVICE": 0x0D,
    "AD_SP_HASH_C192": 0x0E,
    "AD_SP_RANDOMIZER_R192": 0x0F,
    "AD_SM_TK_VALUE": 0x10,
    "AD_SM_OOB_FLAGS": 0x11,
    "AD_PERIPHERAL_CONN_INTERVAL": 0x12,
    "AD_UUID16_SOLICITATION": 0x14,
    "AD_UUID128_SOLICITATION": 0x15,
    "AD_SERVICE_DATA16": 0x16,
    "AD_PUBLIC_TARGET_ADDRESS": 0x17,
    "AD_RANDOM_TARGET_ADDRESS": 0x18,
    "AD_APPEARANCE": 0x19,
    "AD_ADVERTISING_INTERVAL": 0x1A,
    "AD_LE_DEVICE_ADDRESS": 0x1B,
    "AD_LE_ROLE": 0x1C,
    "AD_SP_HASH_C256": 0x1D,
    "AD_SP_RANDOMIZER_R256": 0x1E,
    "AD_UUID32_SOLICITATION": 0x1F,
    "AD_SERVICE_DATA32": 0x20,
    "AD_SERVICE_DATA128": 0x21,
    "AD_LE_SC_CONFIRMATION_VALUE": 0x22,
    "AD_LE_SC_RANDOM_VALUE": 0x23,
    "AD_URI": 0x24,
    "AD_INDOOR_POSITIONING": 0x25,
    "AD_TRANSPORT_DISCOVERY_DATA": 0x26,
    "AD_LE_SUPPORTED_FEATURES": 0x27,
    "AD_CHANNEL_MAP_UPDATE_INDICATION": 0x28,
    "AD_PB_ADV": 0x29,
    "AD_MESH_MESSAGE": 0x2A,
    "AD_MESH_BEACON": 0x2B,
    "AD_BIG_INFO": 0x2C,
    "AD_BROADCAST_CODE": 0x2D,
    "AD_RESOLVABLE_SET_IDENTIFIER": 0x2E,
    "AD_ADVERTISING_INTERVAL_LONG": 0x2F,
    "AD_BROADCAST_NAME": 0x30,
    "AD_ENCRYPTED_ADVERTISING_DATA": 0x31,
    "AD_PA_RESPONSE_TIMING": 0x32,
    "AD_ESL": 0x34,
    "AD_3D_INFORMATION_DATA": 0x3D,
    "AD_MANUFACTURER_SPECIFIC": 0xFF,
}


def test_ad_constants_cover_all_sig_assigned_types():
    for name, value in _SIG_AD_TYPES.items():
        assert getattr(AdvertisingData, name) == value, name


def test_ad_slave_conn_interval_alias_matches_peripheral_name():
    assert AdvertisingData.AD_SLAVE_CONN_INTERVAL == AdvertisingData.AD_PERIPHERAL_CONN_INTERVAL


def test_advertising_data_generic_set_get_roundtrip():
    ad = AdvertisingData()
    ad.set(AdvertisingData.AD_RESOLVABLE_SET_IDENTIFIER, b"\x01\x02\x03")
    assert ad.get(AdvertisingData.AD_RESOLVABLE_SET_IDENTIFIER) == b"\x01\x02\x03"
    decoded = AdvertisingData.from_bytes(ad.to_bytes())
    assert decoded.get(AdvertisingData.AD_RESOLVABLE_SET_IDENTIFIER) == b"\x01\x02\x03"


def test_advertising_data_generic_set_unknown_type_roundtrips():
    ad = AdvertisingData()
    ad.set(0x99, b"\xAA\xBB")  # 0x99 is not an assigned AD type
    decoded = AdvertisingData.from_bytes(ad.to_bytes())
    assert decoded.get(0x99) == b"\xAA\xBB"


def test_advertising_data_generic_get_missing_returns_none():
    assert AdvertisingData().get(AdvertisingData.AD_URI) is None


def test_advertising_data_generic_set_rejects_out_of_range_type():
    with pytest.raises(ValueError):
        AdvertisingData().set(0x100, b"\x00")


def test_advertising_data_generic_set_rejects_non_int_type():
    with pytest.raises(ValueError):
        AdvertisingData().set(0.5, b"\x00")
    with pytest.raises(ValueError):
        AdvertisingData().set(True, b"\x00")


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
