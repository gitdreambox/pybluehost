import pytest
from unittest.mock import MagicMock, patch

from pybluehost.cli.tools.usb import (
    USBDeviceDiagnostics,
    FailureType,
    DriverType,
    _cmd_usb_diagnose,
)


class TestDiagnose:
    def test_errno_13_win32_bthusb(self):
        dev = MagicMock()
        dev.idVendor = 0x8087
        dev.idProduct = 0x0036
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert report.driver_type == DriverType.BTHUSB
        assert "Zadig" in " ".join(report.steps)

    def test_errno_13_win32_unknown(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert len(report.steps) > 0

    def test_errno_minus12_win32_bthusb(self):
        dev = MagicMock()
        dev.idVendor = 0x0A12
        report = USBDeviceDiagnostics.diagnose(dev, errno=-12, platform="win32")
        assert report.failure_type == FailureType.DRIVER_CONFLICT
        assert report.driver_type == DriverType.BTHUSB

    def test_errno_13_linux(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=13, platform="linux")
        assert report.failure_type == FailureType.PERMISSION_DENIED
        assert "udev" in " ".join(report.steps).lower() or "sudo" in " ".join(report.steps).lower()

    def test_errno_2(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=2, platform="win32")
        assert report.failure_type == FailureType.NO_DEVICE

    def test_unknown_errno(self):
        dev = MagicMock()
        report = USBDeviceDiagnostics.diagnose(dev, errno=99, platform="win32")
        assert report.failure_type == FailureType.UNKNOWN


class TestCmdUSBDiagnose:
    def _patch_libusb(self):
        return patch("pybluehost.cli.tools.usb._libusb_library_path", return_value="libusb-1.0.dll")

    def test_no_devices(self, capsys):
        with self._patch_libusb(), patch("pybluehost.cli.tools.usb.usb") as mock_usb:
            mock_usb.core.find.return_value = []
            args = MagicMock()
            ret = _cmd_usb_diagnose(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert "no Bluetooth USB devices found" in captured.out

    def test_device_accessible(self, capsys):
        dev = MagicMock()
        dev.idVendor = 0x0A12
        dev.idProduct = 0x0001
        dev.bDeviceClass = 0xE0
        dev.bDeviceSubClass = 0x01
        dev.bDeviceProtocol = 0x01
        endpoint = MagicMock()
        endpoint.read.return_value = bytes.fromhex("0e 04 01 03 0c 00")
        config = MagicMock()
        config.__getitem__.return_value = MagicMock()
        dev.get_active_configuration.return_value = config

        with self._patch_libusb(), patch("pybluehost.cli.tools.usb.usb") as mock_usb:
            mock_usb.core.find.return_value = [dev]
            mock_usb.util.find_descriptor.return_value = endpoint
            mock_usb.util.endpoint_direction.return_value = mock_usb.util.ENDPOINT_IN
            mock_usb.util.endpoint_type.return_value = mock_usb.util.ENDPOINT_TYPE_INTR
            args = MagicMock()
            ret = _cmd_usb_diagnose(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "0a12:0001" in captured.out
        assert "HCI Reset status: 0x00" in captured.out

    def test_device_bthusb_driver(self, capsys):
        """Device bound to Windows BT driver raises NotImplementedError (errno=-12)."""
        import usb.core
        dev = MagicMock()
        dev.idVendor = 0x0A12
        dev.idProduct = 0x0001
        dev.bDeviceClass = 0xE0
        dev.bDeviceSubClass = 0x01
        dev.bDeviceProtocol = 0x01
        dev.get_active_configuration.side_effect = NotImplementedError("LIBUSB_ERROR_NOT_SUPPORTED")

        with self._patch_libusb(), patch("pybluehost.cli.tools.usb.usb") as mock_usb:
            mock_usb.core.find.return_value = [dev]
            mock_usb.core.USBError = usb.core.USBError
            args = MagicMock()
            ret = _cmd_usb_diagnose(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert "0a12:0001" in captured.out
        assert "DRIVER_CONFLICT" in captured.out
        assert "bthusb" in captured.out.lower() or "Zadig" in captured.out

    def test_device_access_denied(self, capsys):
        """Device access denied by another process (errno=13)."""
        import usb.core
        dev = MagicMock()
        dev.idVendor = 0x0A12
        dev.idProduct = 0x0001
        dev.bDeviceClass = 0xE0
        dev.bDeviceSubClass = 0x01
        dev.bDeviceProtocol = 0x01
        err = usb.core.USBError("Access denied", errno=13)
        dev.get_active_configuration.side_effect = err

        with self._patch_libusb(), patch("pybluehost.cli.tools.usb.usb") as mock_usb:
            mock_usb.core.find.return_value = [dev]
            mock_usb.core.USBError = usb.core.USBError
            args = MagicMock()
            ret = _cmd_usb_diagnose(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert "0a12:0001" in captured.out
        assert "DRIVER_CONFLICT" in captured.out
        assert "errno=13" in captured.out
