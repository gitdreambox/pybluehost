"""Unit tests for the test-transport selection helper module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_primary,
    enforce_same_family,
    family_of,
    find_second_usb_adapter,
    parse_spec,
    usb_spec_bus_address,
    vendor_of,
)


def test_family_of_classifies_specs():
    assert family_of("virtual") == "virtual"
    assert family_of("usb") == "usb"
    assert family_of("usb:vendor=intel") == "usb"
    assert family_of("uart:/dev/ttyUSB0") == "uart"
    assert family_of("uart:/dev/ttyUSB0@921600") == "uart"


def test_parse_spec_accepts_supported_forms():
    assert parse_spec("virtual") == ("virtual", {})
    assert parse_spec("usb") == ("usb", {})
    assert parse_spec("usb:vendor=intel,bus=1,address=4") == (
        "usb",
        {"vendor": "intel", "bus": "1", "address": "4"},
    )
    assert parse_spec("uart:/dev/ttyUSB0@921600") == (
        "uart",
        {"raw": "/dev/ttyUSB0@921600"},
    )


def test_parse_spec_rejects_garbage():
    with pytest.raises(InvalidSpec):
        parse_spec("garbage")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:vendor=qualcomm")


@pytest.mark.parametrize(
    "spec",
    [
        "",
        " ",
        "usb:",
        "usb:vendor=",
        "usb:vendor= ",
        "usb:vendor=intel,",
        "usb:vendor=intel,,bus=1",
        "usb:=intel",
        "usb:vendor",
        "usb:vendor:intel",
        "usb:vendor=intel,bus",
        "usb:vendor=intel,bus=",
        "usb:vendor=intel,bus=abc",
        "usb:vendor=intel,bus=-1",
        "usb:vendor=intel,address=abc",
        "usb:vendor=intel,address=-1",
        "usb:vendor=intel,vendor=realtek",
        "usb:bus=1,bus=2",
        "usb:address=4,address=5",
        "uart:",
        "uart: ",
    ],
)
def test_parse_spec_rejects_empty_duplicate_and_malformed_values(spec):
    with pytest.raises(InvalidSpec):
        parse_spec(spec)


def test_autodetect_returns_virtual_when_no_devices():
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[]):
        assert autodetect_primary() == "virtual"


def test_autodetect_returns_usb_spec_with_bus_address():
    cand = MagicMock()
    cand.vendor = "intel"
    cand.bus = 1
    cand.address = 4
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[cand]):
        assert autodetect_primary() == "usb:vendor=intel,bus=1,address=4"


def test_find_second_usb_adapter_excludes_primary():
    a = MagicMock()
    a.vendor = "intel"
    a.bus = 1
    a.address = 4
    b = MagicMock()
    b.vendor = "intel"
    b.bus = 2
    b.address = 5
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a, b]):
        peer = find_second_usb_adapter(primary_bus=1, primary_address=4)
    assert peer == "usb:vendor=intel,bus=2,address=5"


def test_find_second_usb_adapter_returns_none_when_only_primary():
    a = MagicMock()
    a.vendor = "intel"
    a.bus = 1
    a.address = 4
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a]):
        assert find_second_usb_adapter(primary_bus=1, primary_address=4) is None


def test_same_family_check():
    enforce_same_family(primary="usb:vendor=intel", peer="usb")
    enforce_same_family(primary="virtual", peer="virtual")
    with pytest.raises(SameFamilyError):
        enforce_same_family(primary="usb", peer="virtual")


def test_usb_spec_bus_address_extracts_optional_values():
    assert usb_spec_bus_address("virtual") == (None, None)
    assert usb_spec_bus_address("usb") == (None, None)
    assert usb_spec_bus_address("usb:vendor=intel") == (None, None)
    assert usb_spec_bus_address("usb:vendor=intel,bus=1,address=4") == (1, 4)
    assert usb_spec_bus_address("usb:address=4,bus=1") == (1, 4)
    assert usb_spec_bus_address("usb:bus=1") == (1, None)
    assert usb_spec_bus_address("usb:address=4") == (None, 4)


@pytest.mark.parametrize(
    "spec",
    [
        "usb:",
        "usb:bus=abc",
        "usb:address=abc",
        "usb:bus=-1",
        "usb:address=-1",
        "usb:bus=1,bus=2",
        "usb:address=4,address=5",
        "usb:bus",
    ],
)
def test_usb_spec_bus_address_rejects_invalid_usb_specs(spec):
    with pytest.raises(InvalidSpec):
        usb_spec_bus_address(spec)


def test_vendor_of_extracts_vendor_from_usb_spec():
    assert vendor_of("virtual") is None
    assert vendor_of("usb") is None
    assert vendor_of("uart:/dev/ttyUSB0") is None
    assert vendor_of("usb:vendor=intel") == "intel"
    assert vendor_of("usb:vendor=Intel,bus=1,address=4") == "intel"
    assert vendor_of("usb:bus=1,address=4") is None
