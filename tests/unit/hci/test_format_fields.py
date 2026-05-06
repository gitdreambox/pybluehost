"""Unit tests for individual HCI field formatters."""
from __future__ import annotations

import pytest

from pybluehost.hci.format_fields import (
    format_address,
    format_address_type,
    format_error_code,
    format_le_phy,
    format_role,
    format_rssi,
    format_scan_interval,
    format_status,
    format_uuid16,
)


def test_format_address_public_renders_msb_first():
    assert format_address(b"\x06\x05\x04\x03\x02\x01", addr_type=0) == "Public 01:02:03:04:05:06"


def test_format_address_random_static():
    assert format_address(b"\x66\x55\x44\x33\x22\x11", addr_type=1) == "Random 11:22:33:44:55:66"


def test_format_address_type_known_values():
    assert format_address_type(0) == "PUBLIC"
    assert format_address_type(1) == "RANDOM"
    assert format_address_type(2) == "PUBLIC_IDENTITY"
    assert format_address_type(3) == "RANDOM_IDENTITY"
    assert format_address_type(99) == "0x63"


def test_format_status_success():
    assert format_status(0x00) == "Success"


def test_format_status_known_error():
    assert format_status(0x08) == "Connection_Timeout(0x08)"


def test_format_status_unknown_error_falls_back_to_hex():
    assert format_status(0xFE) == "0xFE"


def test_format_error_code_alias_for_status():
    assert format_error_code(0x00) == "Success"


def test_format_le_phy_known_values():
    assert format_le_phy(1) == "1M"
    assert format_le_phy(2) == "2M"
    assert format_le_phy(3) == "Coded"
    assert format_le_phy(4) == "Coded_S2"
    assert format_le_phy(99) == "0x63"


def test_format_role():
    assert format_role(0) == "Central"
    assert format_role(1) == "Peripheral"


def test_format_scan_interval_renders_milliseconds():
    # 0x0040 * 0.625 ms = 40.0 ms
    assert format_scan_interval(0x0040) == "0x0040 (40.0 ms)"


def test_format_rssi_dbm():
    assert format_rssi(-65) == "-65 dBm"


def test_format_rssi_unavailable():
    # 127 = RSSI not available per Core spec
    assert format_rssi(127) == "N/A"


def test_format_uuid16_known_service():
    # 0x180D = Heart_Rate; sig_db is queried but value will appear in plain form
    # if sig_db isn't loaded — Task 2 wires the lookup. Here we test the no-name case.
    out = format_uuid16(0x180D, sig_lookup=lambda v: None)
    assert out == "0x180D"


def test_format_uuid16_with_lookup_appends_name():
    out = format_uuid16(0x180D, sig_lookup=lambda v: "Heart_Rate")
    assert out == "0x180D (Heart_Rate)"


def test_format_company_id_known():
    from pybluehost.hci.format_fields import format_company_id

    assert format_company_id(0x000F) == "0x000F (Broadcom Corporation)"


def test_format_company_id_unknown():
    from pybluehost.hci.format_fields import format_company_id

    assert format_company_id(0xFFFE).startswith("0xFFFE")


def test_format_uuid16_via_sig_db_default_lookup():
    from pybluehost.hci.format_fields import format_uuid16_default

    # 0x180D = Heart Rate Service in SIG yaml.
    out = format_uuid16_default(0x180D)
    assert out.startswith("0x180D (")
    assert "Heart" in out


def test_format_uuid128_renders_lowercase_canonical():
    from pybluehost.hci.format_fields import format_uuid128

    # On-air little-endian byte order for 0000180d-0000-1000-8000-00805f9b34fb.
    raw = bytes.fromhex("fb349b5f80000080001000000d180000")
    # Canonical xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (big-endian display).
    assert format_uuid128(raw) == "0000180d-0000-1000-8000-00805f9b34fb"


def test_format_class_of_device_phone():
    from pybluehost.hci.format_fields import format_class_of_device

    # 0x5A020C = Phone, Smartphone (CoD layout per Bluetooth assigned numbers):
    # octet0=0x0C -> minor=0x03 (Smartphone); octet1=0x02 -> major=0x02 (Phone).
    out = format_class_of_device(0x5A020C)
    assert out.startswith("0x5A020C")
    assert "Phone" in out


def test_format_ad_type_byte_known():
    from pybluehost.hci.format_fields import format_ad_type

    # AD type 0x09 = Complete Local Name (SIG yaml uses spaces, not underscores).
    out = format_ad_type(0x09)
    assert out.startswith("0x09")
    assert "Local Name" in out
