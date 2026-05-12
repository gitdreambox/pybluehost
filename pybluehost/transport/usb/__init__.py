"""USB HCI transport: ChipInfo registry, USBTransport base, Intel/Realtek subclasses."""

from __future__ import annotations

import asyncio
import collections
import logging
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pybluehost.core.errors import USBAccessDeniedError
from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy
from pybluehost.transport.spec import format_usb_transport_name

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]

from pybluehost.transport.usb.chips import ChipInfo
from pybluehost.transport.usb.errors import NoBluetoothDeviceError, WinUSBDriverError
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
from pybluehost.transport.usb.discovery import (
    _bluetooth_usb_occurrence_indexes,
    _bumble_transport_names,
    _descriptor_string,
    _matches_usb_selection,
)
from pybluehost.transport.usb.diagnostics import (
    DriverType,
    FailureType,
    USBDeviceCheck,
    USBDeviceDiagnosis,
    USBDeviceDiagnostics,
    USBDiagnosticReport,
    _diagnose_intel_version_direct,
    _diagnose_realtek_version_direct,
    _diagnostic_report_checks,
    _find_interrupt_in_endpoint,
)


from pybluehost.transport.usb.base import USBTransport, parse_hci_reset_status
from pybluehost.transport.usb.intel import IntelUSBTransport
from pybluehost.transport.usb.realtek import RealtekLocalVersion, RealtekUSBTransport


class CSRUSBTransport(USBTransport):
    """CSR Bluetooth USB transport.

    CSR8510 currently follows the standard Bluetooth USB HCI path, so it can
    use the base USB transport behavior without vendor-specific initialization.
    """


# --- Known Bluetooth USB chips registry ---
# Transport class references are resolved here after subclass definitions.

KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200",  0x8087, 0x0029, "ibt-20-*",    IntelUSBTransport),
    ChipInfo("intel", "AX201",  0x8087, 0x0026, "ibt-20-*",    IntelUSBTransport),
    ChipInfo("intel", "AX210",  0x8087, 0x0032, "ibt-0040-*",  IntelUSBTransport),
    ChipInfo("intel", "AX211",  0x8087, 0x0033, "ibt-0040-*",  IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*",    IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0A2B, "ibt-12-*",    IntelUSBTransport),
    ChipInfo("intel", "BE200",  0x8087, 0x0036, "ibt-0040-*",  IntelUSBTransport),  # WiFi 7 / BT 5.4
    # Realtek
    ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl8761bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x4853, "rtl8852bu_fw.bin", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw.bin", RealtekUSBTransport),
    # CSR
    ChipInfo("csr", "CSR8510", 0x0A12, 0x0001, "", CSRUSBTransport),
    # BARROT
    ChipInfo("barrot", "BT6.0", 0x33FA, 0x0011, "", USBTransport),
]
