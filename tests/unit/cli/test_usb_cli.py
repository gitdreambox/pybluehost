"""Tests for USB probe CLI command."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from pybluehost.cli.tools.usb import probe_usb_devices, _cmd_usb_probe


def _mock_usb_device(vid, pid, bus=1, addr=1, dev_class=0xE0, sub=0x01, proto=0x01):
    """Create a mock USB device."""
    dev = MagicMock()
    dev.idVendor = vid
    dev.idProduct = pid
    dev.bus = bus
    dev.address = addr
    dev.bDeviceClass = dev_class
    dev.bDeviceSubClass = sub
    dev.bDeviceProtocol = proto
    return dev


# --- probe_usb_devices ---

@patch("pybluehost.cli.tools.usb.usb")
def test_probe_finds_known_intel_chip(mock_usb):
    mock_usb.core.find.return_value = [_mock_usb_device(0x8087, 0x0036)]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "intel"
    assert devices[0]["chip_name"] == "BE200"
    assert devices[0]["vid_pid"] == "8087:0036"


@patch("pybluehost.cli.tools.usb.usb")
def test_probe_finds_known_realtek_chip(mock_usb):
    mock_usb.core.find.return_value = [_mock_usb_device(0x0BDA, 0x8771)]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "realtek"
    assert devices[0]["chip_name"] == "RTL8761B"


@patch("pybluehost.cli.tools.usb.usb")
def test_probe_unknown_bt_class_device(mock_usb):
    """Unknown VID/PID but Bluetooth device class → included as Unknown."""
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x9999, 0x0001, dev_class=0xE0, sub=0x01, proto=0x01)
    ]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "unknown"
    assert devices[0]["chip_name"] == "Unknown BT Device"


@patch("pybluehost.cli.tools.usb.usb")
def test_probe_skips_non_bt_device(mock_usb):
    """Non-BT USB device (e.g. mass storage) is skipped."""
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x1234, 0x5678, dev_class=0x08, sub=0x06, proto=0x50)
    ]
    devices = probe_usb_devices()
    assert len(devices) == 0


@patch("pybluehost.cli.tools.usb.usb")
def test_probe_no_devices(mock_usb):
    mock_usb.core.find.return_value = []
    devices = probe_usb_devices()
    assert devices == []


@patch("pybluehost.cli.tools.usb.usb")
def test_probe_multiple_devices(mock_usb):
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x8087, 0x0036),
        _mock_usb_device(0x0BDA, 0x8771, bus=2, addr=5),
    ]
    devices = probe_usb_devices()
    assert len(devices) == 2
    assert devices[0]["index"] == 1
    assert devices[1]["index"] == 2


def test_probe_pyusb_not_installed():
    with patch("pybluehost.cli.tools.usb.usb", None):
        with pytest.raises(RuntimeError, match="pyusb not installed"):
            probe_usb_devices()


# --- _cmd_usb_probe handler ---

@patch("pybluehost.cli.tools.usb.probe_usb_devices")
def test_cmd_probe_returns_0_with_devices(mock_probe, capsys):
    mock_probe.return_value = [
        {
            "index": 1,
            "vid_pid": "8087:0036",
            "vendor": "intel",
            "chip_name": "BE200",
            "bus": 1,
            "address": 23,
            "device_class": "e0:01:01",
        }
    ]
    args = MagicMock()
    args.verbose = False
    args.intel_tlv = False
    result = _cmd_usb_probe(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "BE200" in out
    assert "8087:0036" in out


@patch("pybluehost.cli.tools.usb.probe_usb_devices")
def test_cmd_probe_returns_0_no_devices(mock_probe, capsys):
    mock_probe.return_value = []
    args = MagicMock()
    args.verbose = False
    args.intel_tlv = False
    result = _cmd_usb_probe(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "No USB Bluetooth devices" in out


@patch("pybluehost.cli.tools.usb.probe_usb_devices", side_effect=RuntimeError("pyusb not installed"))
def test_cmd_probe_returns_1_on_error(mock_probe, capsys):
    args = MagicMock()
    args.verbose = False
    args.intel_tlv = False
    result = _cmd_usb_probe(args)
    assert result == 1
    err = capsys.readouterr().err
    assert "pyusb not installed" in err
