"""USB-transport-specific exception types."""
from __future__ import annotations


class NoBluetoothDeviceError(RuntimeError):
    """Raised when no Bluetooth USB device is found matching the selection criteria."""


class WinUSBDriverError(RuntimeError):
    """Raised when a Windows device is bound to the wrong driver (bthusb.sys
    instead of WinUSB).
    """
