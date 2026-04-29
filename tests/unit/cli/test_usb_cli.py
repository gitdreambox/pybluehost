"""Tests for USB probe CLI command."""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, PropertyMock

from pybluehost.cli.tools.usb import probe_usb_devices, _cmd_usb_probe, _cmd_usb_diagnose


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
    dev.serial_number = None
    dev.manufacturer = None
    dev.product = None
    return dev


def _mock_interface_class_usb_device(vid=0x1234, pid=0x5678):
    """Create a device whose Bluetooth class is declared on interface 0."""
    dev = _mock_usb_device(vid, pid, dev_class=0x00, sub=0x00, proto=0x00)
    interface = MagicMock()
    interface.bInterfaceClass = 0xE0
    interface.bInterfaceSubClass = 0x01
    interface.bInterfaceProtocol = 0x01
    config = MagicMock()
    config.__iter__.return_value = [interface]
    config.__getitem__.return_value = interface
    dev.__iter__.return_value = [config]
    dev.get_active_configuration.return_value = config
    return dev


# --- probe_usb_devices ---

@patch("pybluehost.transport.usb.usb")
def test_probe_finds_known_intel_chip(mock_usb):
    mock_usb.core.find.return_value = [_mock_usb_device(0x8087, 0x0036)]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "intel"
    assert devices[0]["chip_name"] == "BE200"
    assert devices[0]["vid_pid"] == "8087:0036"
    assert devices[0]["bumble_transport_names"] == ["usb:8087:0036"]
    assert devices[0]["id"] == "8087:0036"
    assert devices[0]["transport_names"] == ["usb:8087:0036"]
    assert devices[0]["class_name"] == "Wireless Controller"


@patch("pybluehost.transport.usb.usb")
def test_probe_finds_known_realtek_chip(mock_usb):
    mock_usb.core.find.return_value = [_mock_usb_device(0x0BDA, 0x8771)]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "realtek"
    assert devices[0]["chip_name"] == "RTL8761B"


@patch("pybluehost.transport.usb.usb")
def test_probe_unknown_bt_class_device(mock_usb):
    """Unknown VID/PID but Bluetooth device class → included as Unknown."""
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x9999, 0x0001, dev_class=0xE0, sub=0x01, proto=0x01)
    ]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "unknown"
    assert devices[0]["chip_name"] == "Unknown BT Device"


@patch("pybluehost.transport.usb.usb")
def test_probe_unknown_bt_interface_class_device(mock_usb):
    """Unknown VID/PID with Bluetooth interface class is included."""
    mock_usb.core.find.return_value = [_mock_interface_class_usb_device()]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "unknown"
    assert devices[0]["chip_name"] == "Unknown BT Device"


@patch("pybluehost.transport.usb.usb")
def test_probe_skips_non_bt_device(mock_usb):
    """Non-BT USB device (e.g. mass storage) is skipped."""
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x1234, 0x5678, dev_class=0x08, sub=0x06, proto=0x50)
    ]
    devices = probe_usb_devices()
    assert len(devices) == 0


@patch("pybluehost.transport.usb.usb")
def test_probe_no_devices(mock_usb):
    mock_usb.core.find.return_value = []
    devices = probe_usb_devices()
    assert devices == []


@patch("pybluehost.transport.usb.usb")
def test_probe_multiple_devices(mock_usb):
    mock_usb.core.find.return_value = [
        _mock_usb_device(0x8087, 0x0036),
        _mock_usb_device(0x0BDA, 0x8771, bus=2, addr=5),
    ]
    devices = probe_usb_devices()
    assert len(devices) == 2
    assert devices[0]["index"] == 1
    assert devices[1]["index"] == 2


@patch("pybluehost.transport.usb.usb")
def test_probe_includes_descriptor_strings_and_bumble_serial_name(mock_usb):
    dev = _mock_usb_device(0x0E8D, 0x0808, bus=1, addr=9)
    dev.serial_number = "0000000000000000"
    dev.manufacturer = "MediaTek Inc"
    dev.product = "Airoha Dongle Enterprise"
    mock_usb.core.find.return_value = [dev]

    devices = probe_usb_devices()

    assert devices[0]["serial"] == "0000000000000000"
    assert devices[0]["manufacturer"] == "MediaTek Inc"
    assert devices[0]["product"] == "Airoha Dongle Enterprise"
    assert devices[0]["bumble_transport_names"] == [
        "usb:0E8D:0808",
        "usb:0E8D:0808/0000000000000000",
    ]


def test_probe_pyusb_not_installed():
    with patch("pybluehost.transport.usb.usb", None):
        with pytest.raises(RuntimeError, match="pyusb not installed"):
            probe_usb_devices()


# --- _cmd_usb_probe handler ---

@patch("pybluehost.cli.tools.usb.probe_usb_devices")
def test_cmd_probe_returns_0_with_devices(mock_probe, capsys):
    mock_probe.return_value = [
        {
            "index": 1,
            "vid_pid": "8087:0036",
            "id": "8087:0036",
            "vendor": "intel",
            "chip_name": "BE200",
            "bus": 1,
            "address": 23,
            "device_class": "e0:01:01",
            "device_class_name": "Wireless Controller (e0:01:01)",
            "subclass_protocol": "1/1",
            "bumble_transport_names": ["usb:8087:0036"],
            "class_name": "Wireless Controller",
            "subclass_name": "RF Controller",
            "protocol_name": "Bluetooth Programming Interface",
            "transport_names": ["usb:8087:0036"],
            "serial": None,
            "manufacturer": "Intel",
            "product": "Bluetooth Adapter",
        }
    ]
    args = MagicMock()
    args.verbose = False
    args.intel_tlv = False
    result = _cmd_usb_probe(args)
    assert result == 0
    out = capsys.readouterr().out
    assert "BE200" in out
    assert "ID 8087:0036" in out
    assert "Bumble Transport Names:" in out
    assert "usb:8087:0036" in out
    assert "ID 8087:0036" in out
    assert "Bumble Transport Names: usb:8087:0036" in out
    assert "Bus/Device:             001/023" in out
    assert "Class:                  Wireless Controller" in out
    assert "Subclass/Protocol:      RF Controller / Bluetooth Programming Interface" in out
    assert "Manufacturer:           Intel" in out
    assert "Product:                Bluetooth Adapter" in out


@patch("pybluehost.cli.tools.usb.probe_usb_devices")
def test_cmd_probe_formats_serial_transport_name_and_color(mock_probe, capsys):
    mock_probe.return_value = [
        {
            "index": 1,
            "vid_pid": "0e8d:0808",
            "id": "0E8D:0808",
            "vendor": "unknown",
            "chip_name": "Unknown BT Device",
            "bus": 1,
            "address": 9,
            "device_class": "00:00:00",
            "class_name": "Device",
            "subclass_name": "0",
            "protocol_name": "0",
            "transport_names": ["usb:0E8D:0808", "usb:0E8D:0808/0000000000000000"],
            "serial": "0000000000000000",
            "manufacturer": "MediaTek Inc",
            "product": "Airoha Dongle Enterprise",
        }
    ]
    args = MagicMock()
    args.verbose = False
    args.intel_tlv = False
    args.color = True

    result = _cmd_usb_probe(args)

    assert result == 0
    out = capsys.readouterr().out
    assert "ID \x1b[" in out
    assert "0E8D:0808" in out
    assert "usb:0E8D:0808 or usb:0E8D:0808/0000000000000000" in out
    assert "Serial:" in out
    assert "0000000000000000" in out


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


@patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")
@patch("pybluehost.transport.usb.usb")
def test_cmd_diagnose_reports_hci_reset_success(mock_usb, mock_libusb, capsys):
    dev = _mock_interface_class_usb_device()
    endpoint = MagicMock()
    endpoint.read.return_value = bytes.fromhex("0e 04 01 03 0c 00")
    mock_usb.core.find.return_value = [dev]
    mock_usb.util.find_descriptor.return_value = endpoint
    mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
    mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR

    result = _cmd_usb_diagnose(MagicMock())

    assert result == 0
    out = capsys.readouterr().out
    assert "[OK] libusb backend" in out
    assert "[OK] enumerate Bluetooth USB" in out
    assert "[OK] USB access" in out
    assert "[OK] WinUSB/libusb driver access" in out
    assert "[OK] HCI Reset command sent" in out
    assert "[OK] HCI Reset event received" in out
    assert "[OK] HCI Reset status: 0x00" in out


@patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")
@patch("pybluehost.transport.usb.usb")
def test_cmd_diagnose_reports_hci_reset_status_failure(mock_usb, mock_libusb, capsys):
    dev = _mock_interface_class_usb_device()
    endpoint = MagicMock()
    endpoint.read.return_value = bytes.fromhex("0e 04 01 03 0c 0c")
    mock_usb.core.find.return_value = [dev]
    mock_usb.util.find_descriptor.return_value = endpoint
    mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
    mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR

    result = _cmd_usb_diagnose(MagicMock())

    assert result == 1
    out = capsys.readouterr().out
    assert "[FAIL] HCI Reset status: 0x0C" in out
    assert "firmware load" in out
