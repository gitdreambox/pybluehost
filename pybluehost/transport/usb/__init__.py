"""USB HCI transport package.

This is a thin re-export shim. The implementation lives in sibling modules:

- ``chips``       : ChipInfo dataclass identifying known USB chips
- ``errors``      : Package-specific exception types
- ``discovery``   : Pure-function helpers for enumerating Bluetooth USB devices
- ``diagnostics`` : Diagnostic probes used when a device fails to open
- ``base``        : USBTransport abstract base class
- ``intel``       : IntelUSBTransport (AX200/AX201/AX210/BE200/...)
- ``realtek``     : RealtekUSBTransport (RTL8761/RTL8852/...)
- ``csr``         : CSRUSBTransport (CSR8510 and similar firmware-less dongles)

External callers should ``from pybluehost.transport.usb import <symbol>`` —
the layout above is an implementation detail and may change.
"""
from __future__ import annotations

# Lazy import: pyusb is optional. The package-level ``usb`` attribute is the
# canonical patch target for tests; sibling modules read it via _usb() helpers.
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]

from pybluehost.transport.usb.base import USBTransport, parse_hci_reset_status
from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.csr import CSRUSBTransport
from pybluehost.transport.usb.diagnostics import (
    DriverType,
    FailureType,
    USBDeviceCheck,
    USBDeviceDiagnosis,
    USBDeviceDiagnostics,
    USBDiagnosticReport,
)
from pybluehost.transport.usb.discovery import (
    DeviceCandidate,
    format_usb_class,
    get_usb_endpoints,
    is_bluetooth_usb_class,
    is_bluetooth_usb_device,
    iter_usb_interfaces,
    known_chip_for,
    known_usb_vendors,
    usb_class_tuple,
)
from pybluehost.transport.usb.errors import (
    NoBluetoothDeviceError,
    WinUSBDriverError,
)
from pybluehost.transport.usb.intel import IntelUSBTransport
from pybluehost.transport.usb.realtek import RealtekLocalVersion, RealtekUSBTransport

# KNOWN_CHIPS must be defined AFTER subclass imports so chip.transport_class
# fields can reference real classes.
KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*",   IntelUSBTransport),
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*",   IntelUSBTransport),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*",   IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0A2B, "ibt-12-*",   IntelUSBTransport),
    ChipInfo("intel", "BE200",  0x8087, 0x0036, "ibt-0040-*", IntelUSBTransport),
    # Realtek
    ChipInfo("realtek", "RTL8761B",  0x0BDA, 0x8771, "rtl8761bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x4853, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw.bin",  RealtekUSBTransport),
    # CSR
    ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport),
    # BARROT (no firmware, uses generic USBTransport)
    ChipInfo("barrot", "BT6.0", 0x33FA, 0x0011, "", USBTransport),
]

__all__ = [
    # Core types
    "ChipInfo",
    "DeviceCandidate",
    # Transport classes
    "USBTransport",
    "IntelUSBTransport",
    "RealtekUSBTransport",
    "CSRUSBTransport",
    # Diagnostics
    "DriverType",
    "FailureType",
    "RealtekLocalVersion",
    "USBDeviceCheck",
    "USBDeviceDiagnosis",
    "USBDeviceDiagnostics",
    "USBDiagnosticReport",
    # Discovery helpers
    "format_usb_class",
    "get_usb_endpoints",
    "is_bluetooth_usb_class",
    "is_bluetooth_usb_device",
    "iter_usb_interfaces",
    "known_chip_for",
    "known_usb_vendors",
    "usb_class_tuple",
    # Utilities
    "parse_hci_reset_status",
    # Exceptions
    "NoBluetoothDeviceError",
    "WinUSBDriverError",
    # Chip registry
    "KNOWN_CHIPS",
]
