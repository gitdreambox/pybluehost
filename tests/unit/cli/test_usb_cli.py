"""Tests for USB probe CLI command."""

import pytest
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

@patch("pybluehost.cli.tools.usb.usb")
def test_probe_finds_known_intel_chip(mock_usb):
    mock_usb.core.find.return_value = [_mock_usb_device(0x8087, 0x0036)]
    devices = probe_usb_devices()
    assert len(devices) == 1
    assert devices[0]["vendor"] == "intel"
    assert devices[0]["chip_name"] == "BE200"
    assert devices[0]["vid_pid"] == "8087:0036"
    assert devices[0]["id"] == "8087:0036"
    assert devices[0]["transport_names"] == ["usb:8087:0036"]
    assert devices[0]["class_name"] == "Wireless Controller"


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
def test_probe_unknown_bt_interface_class_device(mock_usb):
    """Unknown VID/PID with Bluetooth interface class is included."""
    mock_usb.core.find.return_value = [_mock_interface_class_usb_device()]
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
            "id": "8087:0036",
            "vendor": "intel",
            "chip_name": "BE200",
            "bus": 1,
            "address": 23,
            "device_class": "e0:01:01",
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
@patch("pybluehost.cli.tools.usb.usb")
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
@patch("pybluehost.cli.tools.usb.usb")
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


@patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")
@patch("pybluehost.cli.tools.usb.usb")
def test_cmd_diagnose_tries_intel_reset_when_hci_reset_event_times_out(
    mock_usb, mock_libusb, capsys
):
    dev = _mock_usb_device(0x8087, 0x0036)
    rebooted_dev = _mock_usb_device(0x8087, 0x0036, addr=2)
    config = MagicMock()
    config.__getitem__.return_value = MagicMock()
    dev.get_active_configuration.return_value = config
    rebooted_dev.get_active_configuration.return_value = config
    endpoint = MagicMock()
    endpoint.read.side_effect = [
        Exception("flush done"),
        Exception("standard reset timeout"),
        bytes.fromhex("0e 04 01 01 fc 00"),
        Exception("flush done"),
        bytes.fromhex("0e 04 01 03 0c 00"),
        bytes.fromhex("0e 08 01 05 fc 00 1c 01 03"),
    ]
    mock_usb.core.find.side_effect = [[dev], rebooted_dev]
    mock_usb.util.find_descriptor.return_value = endpoint
    mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
    mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR

    result = _cmd_usb_diagnose(MagicMock())

    assert result == 0
    standard_reset = bytes.fromhex("03 0c 00")
    intel_reset = bytes.fromhex("01 fc 08 01 01 01 00 00 00 00 00")
    intel_read_version = bytes.fromhex("05 fc 01 ff")
    sent_commands = [call.args[4] for call in dev.ctrl_transfer.call_args_list]
    rebooted_commands = [call.args[4] for call in rebooted_dev.ctrl_transfer.call_args_list]
    assert sent_commands == [standard_reset, intel_reset]
    assert rebooted_commands == [standard_reset, intel_read_version]
    out = capsys.readouterr().out
    assert "[FAIL] HCI Reset event received" in out
    assert "[OK] Intel Reset command sent" in out
    assert "[OK] Intel Reset event received" in out
    assert "[OK] Intel reboot complete" in out
    assert "[OK] Post-Intel HCI Reset status: 0x00" in out
    assert "Intel Version:" in out
    assert "image_type=OPERATIONAL" in out


@patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")
@patch("pybluehost.cli.tools.usb.usb")
def test_cmd_diagnose_treats_intel_reset_disconnect_as_success(
    mock_usb, mock_libusb, capsys
):
    dev = _mock_usb_device(0x8087, 0x0036)
    rebooted_dev = _mock_usb_device(0x8087, 0x0036, addr=2)
    config = MagicMock()
    config.__getitem__.return_value = MagicMock()
    dev.get_active_configuration.return_value = config
    rebooted_dev.get_active_configuration.return_value = config
    disconnect = Exception("No such device")
    disconnect.errno = 19
    endpoint = MagicMock()
    endpoint.read.side_effect = [
        Exception("flush done"),
        Exception("standard reset timeout"),
        disconnect,
        Exception("flush done"),
        bytes.fromhex("0e 04 01 03 0c 00"),
        bytes.fromhex("0e 08 01 05 fc 00 1c 01 03"),
    ]
    mock_usb.core.find.side_effect = [[dev], rebooted_dev]
    mock_usb.util.find_descriptor.return_value = endpoint
    mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
    mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR

    result = _cmd_usb_diagnose(MagicMock())

    assert result == 0
    out = capsys.readouterr().out
    assert "[OK] Intel Reset command sent" in out
    assert "device disconnected/re-enumerating" in out
    assert "[OK] Intel reboot complete" in out
    assert "Intel Version:" in out


@patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")
@patch("pybluehost.cli.tools.usb.usb")
def test_cmd_diagnose_warns_firmware_load_needed_for_bootloader(
    mock_usb, mock_libusb, capsys
):
    dev = _mock_usb_device(0x8087, 0x0036)
    rebooted_dev = _mock_usb_device(0x8087, 0x0036, addr=2)
    config = MagicMock()
    config.__getitem__.return_value = MagicMock()
    dev.get_active_configuration.return_value = config
    rebooted_dev.get_active_configuration.return_value = config
    endpoint = MagicMock()
    endpoint.read.side_effect = [
        Exception("flush done"),
        Exception("standard reset timeout"),
        Exception("No such device"),
        Exception("flush done"),
        bytes.fromhex("0e 04 01 03 0c 01"),
        bytes.fromhex("0e 08 01 05 fc 00 1c 01 01"),
    ]
    mock_usb.core.find.side_effect = [[dev], rebooted_dev]
    mock_usb.util.find_descriptor.return_value = endpoint
    mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
    mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR

    result = _cmd_usb_diagnose(MagicMock())

    assert result == 0
    out = capsys.readouterr().out
    assert "Post-Intel HCI Reset status: 0x01 indicates firmware load is needed" in out
    assert "Intel Read Version image_type=BOOTLOADER indicates firmware load is needed" in out
    assert "Confirm before starting Intel firmware load" in out
