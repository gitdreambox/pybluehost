"""Tests for USBTransport.list_devices() and auto_detect bus/address filtering."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from pybluehost.transport.usb import (
    DeviceCandidate,
    NoBluetoothDeviceError,
    USBTransport,
)


def _make_dev(vid: int, pid: int, bus: int, address: int) -> MagicMock:
    dev = MagicMock()
    dev.idVendor = vid
    dev.idProduct = pid
    dev.bus = bus
    dev.address = address
    return dev


def test_device_candidate_exposes_chip_metadata_and_is_frozen():
    intel = _make_dev(0x8087, 0x0032, bus=1, address=4)
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            candidate = USBTransport.list_devices()[0]

    assert isinstance(candidate, DeviceCandidate)
    assert candidate.vendor == "intel"
    assert candidate.name == "AX210"
    assert candidate.bus == 1
    assert candidate.address == 4
    with pytest.raises(FrozenInstanceError):
        candidate.bus = 9


def test_list_devices_returns_known_chips_only():
    intel = _make_dev(0x8087, 0x0032, bus=1, address=4)
    other = _make_dev(0x1234, 0x5678, bus=1, address=5)

    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel, other]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            candidates = USBTransport.list_devices()

    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, DeviceCandidate)
    assert cand.vendor == "intel"
    assert cand.bus == 1
    assert cand.address == 4
    assert cand.chip_info.name == "AX210"


def test_list_devices_returns_empty_when_no_devices():
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = []
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            assert USBTransport.list_devices() == []


def test_list_devices_returns_empty_when_pyusb_unavailable():
    with patch("pybluehost.transport.usb.usb", None):
        assert USBTransport.list_devices() == []


def test_list_devices_returns_empty_when_enumeration_fails():
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.side_effect = RuntimeError("backend failed")
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            assert USBTransport.list_devices() == []


def test_auto_detect_bus_address_filters_to_specific_adapter():
    intel_a = _make_dev(0x8087, 0x0032, bus=1, address=4)
    intel_b = _make_dev(0x8087, 0x0032, bus=2, address=5)

    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel_a, intel_b]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            t = USBTransport.auto_detect(vendor="intel", bus=2, address=5)

    assert t._device is intel_b


def test_auto_detect_bus_address_no_match_raises_with_location():
    intel = _make_dev(0x8087, 0x0032, bus=1, address=4)
    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.return_value = [intel]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            with pytest.raises(NoBluetoothDeviceError) as exc_info:
                USBTransport.auto_detect(vendor="intel", bus=9, address=9)

    assert "No supported intel Bluetooth USB device found" in str(exc_info.value)
    assert "bus=9 address=9" in str(exc_info.value)


def test_auto_detect_disables_generic_fallback_when_location_filter_is_set():
    bt_device = _make_dev(0x9999, 0x0001, bus=3, address=7)
    bt_device.bDeviceClass = 0xE0
    bt_device.bDeviceSubClass = 0x01
    bt_device.bDeviceProtocol = 0x01

    with patch("pybluehost.transport.usb.usb") as usb_mod:
        usb_mod.core.find.side_effect = [[], [bt_device]]
        with patch.object(USBTransport, "_get_usb_backend", return_value=None):
            with pytest.raises(NoBluetoothDeviceError):
                USBTransport.auto_detect(bus=3)

    assert usb_mod.core.find.call_count == 1
