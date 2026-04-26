import pytest
from unittest.mock import MagicMock

from pybluehost.cli.diagnostics import (
    USBDeviceDiagnostics,
    FailureType,
    DriverType,
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
