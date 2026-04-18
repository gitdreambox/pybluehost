"""USB HCI transport: ChipInfo registry, USBTransport base, Intel/Realtek subclasses."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy

if TYPE_CHECKING:
    pass

# Lazy import: pyusb is optional
try:
    import usb
    import usb.core
    import usb.util
except ImportError:
    usb = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ChipInfo:
    """Describes a known Bluetooth USB chip: vendor, VID/PID, firmware pattern."""

    vendor: str
    name: str
    vid: int
    pid: int
    firmware_pattern: str
    transport_class: type | None  # filled after subclass definitions


class NoBluetoothDeviceError(RuntimeError):
    """No supported Bluetooth USB device was found."""


class WinUSBDriverError(RuntimeError):
    """Device is not bound to WinUSB driver (Windows)."""


class USBTransport(Transport):
    """USB HCI transport via pyusb (WinUSB on Windows, libusb on Linux)."""

    def __init__(
        self,
        device: Any,
        chip_info: ChipInfo | None = None,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
        extra_fw_dirs: list | None = None,
    ) -> None:
        super().__init__()
        self._device = device
        self._chip_info = chip_info
        self._firmware_policy = firmware_policy
        self._extra_fw_dirs = extra_fw_dirs or []
        self._is_open = False
        self._reader_tasks: list[asyncio.Task] = []  # type: ignore[type-arg]

    @classmethod
    def auto_detect(
        cls,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
    ) -> USBTransport:
        """Enumerate USB devices, match KNOWN_CHIPS, return correct subclass instance."""
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb"
            )

        # 1. Search known chips by VID/PID
        all_devices = list(usb.core.find(find_all=True))
        for dev in all_devices:
            for chip in KNOWN_CHIPS:
                if dev.idVendor == chip.vid and dev.idProduct == chip.pid:
                    transport_cls = chip.transport_class or cls
                    return transport_cls(
                        device=dev,
                        chip_info=chip,
                        firmware_policy=firmware_policy,
                    )

        # 2. Fallback: look for BT device class (0xE0, 0x01, 0x01)
        bt_devices = list(
            usb.core.find(
                find_all=True,
                bDeviceClass=0xE0,
                bDeviceSubClass=0x01,
                bDeviceProtocol=0x01,
            )
        )
        if bt_devices:
            dev = bt_devices[0]
            return cls(device=dev, firmware_policy=firmware_policy)

        raise NoBluetoothDeviceError(
            "No supported Bluetooth USB device found. "
            "Ensure your adapter is plugged in and (on Windows) has the WinUSB driver."
        )

    async def open(self) -> None:
        """Open USB transport: claim interface, locate endpoints, initialize."""
        if sys.platform == "win32":
            self._verify_winusb_driver()

        # Claim HCI interface (interface 0)
        # Locate endpoints: Control EP0, Interrupt IN, Bulk IN/OUT, Isoch IN/OUT
        # These would be set up via pyusb in a real environment
        await self._initialize()
        self._is_open = True

    async def close(self) -> None:
        """Close USB transport: cancel readers, release interface."""
        for task in self._reader_tasks:
            task.cancel()
        self._reader_tasks.clear()
        self._is_open = False

    async def send(self, data: bytes) -> None:
        """Route by H4 packet type indicator byte."""
        if not data:
            raise ValueError("Cannot send empty data")
        packet_type = data[0]
        payload = data[1:]
        if packet_type == 0x01:
            await self._control_out(payload)  # HCI Command → Control EP
        elif packet_type == 0x02:
            await self._bulk_out(payload)  # ACL Data → Bulk OUT
        elif packet_type == 0x03:
            await self._isoch_out(payload)  # SCO Data → Isoch OUT
        else:
            raise ValueError(
                f"Unknown H4 packet type: 0x{packet_type:02X}. "
                "Expected 0x01 (Command), 0x02 (ACL), or 0x03 (SCO)."
            )

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def info(self) -> TransportInfo:
        name = self._chip_info.name if self._chip_info else "Unknown"
        vendor = self._chip_info.vendor if self._chip_info else "unknown"
        return TransportInfo(
            type="usb",
            description=f"USB Bluetooth: {vendor} {name}",
            platform=sys.platform,
            details={
                "vendor": vendor,
                "name": name,
                "vid": hex(self._chip_info.vid) if self._chip_info else None,
                "pid": hex(self._chip_info.pid) if self._chip_info else None,
            },
        )

    async def _initialize(self) -> None:
        """Override in subclasses for firmware loading. Default: no-op."""

    async def _control_out(self, data: bytes) -> None:
        """Send HCI command via USB control transfer (EP0)."""
        # Real implementation uses usb.core.Device.ctrl_transfer
        raise NotImplementedError("USB control transfer not available in mock")

    async def _bulk_out(self, data: bytes) -> None:
        """Send ACL data via USB bulk OUT endpoint."""
        raise NotImplementedError("USB bulk transfer not available in mock")

    async def _isoch_out(self, data: bytes) -> None:
        """Send SCO data via USB isochronous OUT endpoint."""
        raise NotImplementedError("USB isochronous transfer not available in mock")

    def _verify_winusb_driver(self) -> None:
        """Windows: check device is bound to WinUSB, not Microsoft Bluetooth driver."""
        # On Windows, we'd check the driver via registry or setupapi
        # If bound to bthusb.sys, raise WinUSBDriverError with instructions


class IntelUSBTransport(USBTransport):
    """Intel Bluetooth USB transport. Firmware loading implemented in Plan 3b."""

    async def _initialize(self) -> None:
        """Placeholder — full firmware loading sequence implemented in Plan 3b."""


class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport. Firmware loading implemented in Plan 3b."""

    async def _initialize(self) -> None:
        """Placeholder — full firmware loading sequence implemented in Plan 3b."""


# --- Known Bluetooth USB chips registry ---
# Transport class references are resolved here after subclass definitions.

KNOWN_CHIPS: list[ChipInfo] = [
    # Intel
    ChipInfo("intel", "AX200", 0x8087, 0x0029, "ibt-20-*", IntelUSBTransport),
    ChipInfo("intel", "AX201", 0x8087, 0x0026, "ibt-20-*", IntelUSBTransport),
    ChipInfo("intel", "AX210", 0x8087, 0x0032, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AX211", 0x8087, 0x0033, "ibt-0040-*", IntelUSBTransport),
    ChipInfo("intel", "AC9560", 0x8087, 0x0025, "ibt-18-*", IntelUSBTransport),
    ChipInfo("intel", "AC8265", 0x8087, 0x0A2B, "ibt-12-*", IntelUSBTransport),
    # Realtek
    ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl8761b_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852CE", 0x0BDA, 0x4853, "rtl8852cu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw", RealtekUSBTransport),
]
