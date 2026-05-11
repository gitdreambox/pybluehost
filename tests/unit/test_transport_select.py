"""Unit tests for the test-transport selection helper module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests._transport_select import (
    InvalidSpec,
    SameFamilyError,
    autodetect_primary,
    autodetect_usb_candidates,
    enforce_same_family,
    family_of,
    find_second_usb_adapter,
    parse_spec,
    uart_spec_port_baud,
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
    assert parse_spec("usb:vendor=barrot,bus=1,address=16") == (
        "usb",
        {"vendor": "barrot", "bus": "1", "address": "16"},
    )
    assert parse_spec("usb:33FA:0012#1") == (
        "usb",
        {"vid": "33fa", "pid": "0012", "occurrence": "1"},
    )
    assert parse_spec("usb:0A12:0001#2") == (
        "usb",
        {"vid": "0a12", "pid": "0001", "occurrence": "2"},
    )
    assert parse_spec("uart:/dev/ttyUSB0@921600") == (
        "uart",
        {"raw": "/dev/ttyUSB0@921600"},
    )


def test_transport_spec_does_not_keep_separate_usb_vendor_registry():
    source = Path("pybluehost/transport/spec.py").read_text(encoding="utf-8")

    assert "_VALID_VENDORS" not in source
    assert "known_usb_vendors" in source


def test_parse_spec_rejects_garbage():
    with pytest.raises(InvalidSpec):
        parse_spec("garbage")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:vendor=qualcomm")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:1234")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:1234:5678")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:0E8D:0808/0000000000000000")
    with pytest.raises(InvalidSpec):
        parse_spec("usb:1234:5678#0")


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
    cand.transport_name = "usb:8087:0032#1"
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[cand]):
        assert autodetect_primary() == "usb:8087:0032#1"


def test_autodetect_usb_candidates_returns_all_concrete_specs():
    a = MagicMock()
    a.vendor = "intel"
    a.bus = 1
    a.address = 4
    a.transport_name = "usb:8087:0032#1"
    b = MagicMock()
    b.vendor = "csr"
    b.bus = 2
    b.address = 5
    b.transport_name = "usb:0A12:0001#1"

    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a, b]):
        assert autodetect_usb_candidates() == [
            "usb:8087:0032#1",
            "usb:0A12:0001#1",
        ]


def test_autodetect_wraps_list_devices_errors():
    with patch(
        "pybluehost.transport.usb.USBTransport.list_devices",
        side_effect=RuntimeError("usb backend failed"),
    ):
        with pytest.raises(InvalidSpec, match="Unable to enumerate USB transports"):
            autodetect_primary()


def test_find_second_usb_adapter_excludes_primary():
    a = MagicMock()
    a.vendor = "intel"
    a.bus = 1
    a.address = 4
    a.transport_name = "usb:0A12:0001#1"
    b = MagicMock()
    b.vendor = "intel"
    b.bus = 2
    b.address = 5
    b.transport_name = "usb:0A12:0001#2"
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a, b]):
        peer = find_second_usb_adapter(primary_spec="usb:0A12:0001#1")
    assert peer == "usb:0A12:0001#2"


def test_find_second_usb_adapter_returns_none_when_only_primary():
    a = MagicMock()
    a.vendor = "intel"
    a.bus = 1
    a.address = 4
    a.transport_name = "usb:0A12:0001#1"
    with patch("pybluehost.transport.usb.USBTransport.list_devices", return_value=[a]):
        assert find_second_usb_adapter(primary_spec="usb:0A12:0001#1") is None


def test_find_second_usb_adapter_returns_none_when_primary_identity_unknown():
    with patch("pybluehost.transport.usb.USBTransport.list_devices") as list_devices:
        assert find_second_usb_adapter(primary_spec="usb") is None

    list_devices.assert_not_called()


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


def test_uart_spec_port_baud_extracts_port_and_default_baudrate():
    assert uart_spec_port_baud("uart:/dev/ttyUSB0") == ("/dev/ttyUSB0", 115200)
    assert uart_spec_port_baud("uart:COM3") == ("COM3", 115200)


def test_uart_spec_port_baud_extracts_explicit_baudrate():
    assert uart_spec_port_baud("uart:/dev/ttyUSB0@921600") == (
        "/dev/ttyUSB0",
        921600,
    )


@pytest.mark.parametrize(
    "spec",
    [
        "virtual",
        "usb",
        "uart:@115200",
        "uart:/dev/ttyUSB0@",
        "uart:/dev/ttyUSB0@fast",
        "uart:/dev/ttyUSB0@-1",
        "uart:/dev/ttyUSB0@0",
    ],
)
def test_uart_spec_port_baud_rejects_non_uart_or_malformed_uart_specs(spec):
    with pytest.raises(InvalidSpec):
        uart_spec_port_baud(spec)


def test_vendor_of_extracts_vendor_from_usb_spec():
    assert vendor_of("virtual") is None
    assert vendor_of("usb") is None
    assert vendor_of("uart:/dev/ttyUSB0") is None
    assert vendor_of("usb:vendor=intel") == "intel"
    assert vendor_of("usb:vendor=Intel,bus=1,address=4") == "intel"
    assert vendor_of("usb:vendor=BARROT,bus=1,address=16") == "barrot"
    assert vendor_of("usb:bus=1,address=4") is None
