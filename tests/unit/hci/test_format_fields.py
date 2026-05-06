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
