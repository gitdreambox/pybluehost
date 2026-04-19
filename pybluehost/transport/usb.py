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
    """Intel Bluetooth USB transport with firmware loading.

    Intel firmware loading sequence:
    1. HCI_Intel_Read_Version (vendor 0xFC05) → get hw_variant, fw_variant
    2. If fw_variant == 0x03 (operational) → skip, firmware already loaded
    3. If fw_variant == 0x06 (bootloader) → proceed with firmware load:
       a. Find firmware file via FirmwareManager
       b. HCI_Intel_Enter_Mfg_Mode (vendor 0xFC11)
       c. Stream firmware in ≤252-byte chunks via vendor command 0xFC09
       d. HCI_Intel_Reset (vendor 0xFC01)
       e. HCI_Intel_Read_Version again to verify fw_variant == 0x03
    """

    # Intel vendor command OCFs
    _INTEL_READ_VERSION = 0x05
    _INTEL_ENTER_MFG = 0x11
    _INTEL_WRITE_PATCH = 0x09  # Send firmware data chunk
    _INTEL_RESET = 0x01

    # Firmware variant codes
    _FW_VARIANT_OPERATIONAL = 0x03
    _FW_VARIANT_BOOTLOADER = 0x06

    async def _initialize(self) -> None:
        """Intel 6-step firmware loading sequence."""
        # Step 1: Read Version
        version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
        fw_variant = self._parse_fw_variant(version_data)

        # Step 2: Check if firmware is already loaded
        if fw_variant == self._FW_VARIANT_OPERATIONAL:
            return  # Already operational, no firmware loading needed

        # Step 3: Find firmware file
        fw_path = self._find_firmware()

        # Step 4: Enter manufacturer mode
        await self._send_intel_vendor_cmd(self._INTEL_ENTER_MFG)

        # Step 5: Stream firmware in chunks
        fw_data = fw_path.read_bytes()
        chunks = self._split_firmware(fw_data)
        for chunk in chunks:
            await self._send_intel_vendor_cmd(self._INTEL_WRITE_PATCH, chunk)

        # Step 6: Intel Reset
        await self._send_intel_vendor_cmd(self._INTEL_RESET)

        # Step 7: Verify firmware loaded (re-read version)
        version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
        fw_variant = self._parse_fw_variant(version_data)
        if fw_variant != self._FW_VARIANT_OPERATIONAL:
            raise RuntimeError(
                f"Intel firmware load failed: fw_variant=0x{fw_variant:02X}, "
                f"expected 0x{self._FW_VARIANT_OPERATIONAL:02X} (operational)"
            )

    async def _send_intel_vendor_cmd(
        self, ocf: int, params: bytes = b""
    ) -> bytes:
        """Send Intel vendor command (OGF=0x3F) and await Command Complete Event."""
        # Opcode: OGF=0x3F (vendor), OCF given
        opcode = (0x3F << 10) | ocf
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        return await self._wait_for_event()

    def _parse_fw_variant(self, event_data: bytes) -> int:
        """Extract fw_variant from Intel Read Version response."""
        # Event structure: event_code(1) + param_len(1) + num_hci_cmds(1) +
        #                  opcode(2) + status(1) + hw_platform(1) + hw_variant(1) + fw_variant(1) + ...
        if len(event_data) >= 9:
            return event_data[8]
        return 0xFF  # Unknown

    def _find_firmware(self) -> "Path":
        """Locate Intel firmware file using FirmwareManager."""
        from pathlib import Path
        import glob as glob_mod

        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        # Try exact match from chip_info firmware_pattern
        pattern = self._chip_info.firmware_pattern if self._chip_info else "ibt-*"
        # Search each directory for pattern match
        for search_dir in mgr._search_dirs():
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return matches[0]

        # If no glob match, try the pattern as a filename
        return mgr.find(pattern)

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event from device. Override in tests."""
        raise NotImplementedError(
            "Real USB event reading requires hardware. "
            "Mock this method in tests."
        )


class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport with firmware loading.

    Realtek firmware loading sequence:
    1. HCI_Realtek_Read_ROM_Version (vendor 0xFC6D) → lmp_subversion, rom_version
    2. Check if firmware download is needed
    3. Find firmware + optional config files via FirmwareManager
    4. Download firmware in ≤252-byte chunks (vendor cmd 0xFC20)
    5. HCI_Reset → verify
    """

    # Realtek vendor command OCFs
    _RTK_READ_ROM_VERSION = 0x6D
    _RTK_DOWNLOAD_FW = 0x20

    async def _initialize(self) -> None:
        """Realtek 5-step firmware loading sequence."""
        # Step 1: Read ROM Version
        rom_data = await self._send_realtek_vendor_cmd(self._RTK_READ_ROM_VERSION)
        rom_version = self._parse_rom_version(rom_data)

        # Step 2: Check if firmware download is needed
        if not self._needs_firmware_download(rom_version):
            return

        # Step 3: Find firmware file
        fw_path = self._find_firmware()

        # Step 4: Download firmware in chunks
        fw_data = fw_path.read_bytes()
        chunks = self._split_firmware(fw_data)
        for i, chunk in enumerate(chunks):
            # Realtek download command includes chunk index
            index_byte = i.to_bytes(1, "little") if i < 256 else b"\xff"
            await self._send_realtek_vendor_cmd(
                self._RTK_DOWNLOAD_FW, index_byte + chunk
            )

        # Step 5: HCI Reset to activate firmware
        reset_opcode = (0x03 << 10) | 0x03  # OGF=0x03, OCF=0x03 (HCI_Reset)
        reset_cmd = reset_opcode.to_bytes(2, "little") + b"\x00"
        await self._control_out(reset_cmd)
        await self._wait_for_event()

    async def _send_realtek_vendor_cmd(
        self, ocf: int, params: bytes = b""
    ) -> bytes:
        """Send Realtek vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        return await self._wait_for_event()

    def _parse_rom_version(self, event_data: bytes) -> int:
        """Extract ROM version from Realtek Read ROM Version response."""
        # Event: event_code(1) + param_len(1) + num_hci_cmds(1) +
        #        opcode(2) + status(1) + rom_version(1)
        if len(event_data) >= 7:
            return event_data[6]
        return 0xFF

    def _needs_firmware_download(self, rom_version: int = 0) -> bool:
        """Determine if firmware download is needed based on ROM version."""
        # In practice, most Realtek chips always need firmware download
        # after power cycle. Override in tests.
        return True

    def _find_firmware(self) -> "Path":
        """Locate Realtek firmware file using FirmwareManager."""
        mgr = FirmwareManager(
            vendor="realtek",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        fw_name = self._chip_info.firmware_pattern if self._chip_info else "rtl_fw"
        return mgr.find(fw_name)

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event from device. Override in tests."""
        raise NotImplementedError(
            "Real USB event reading requires hardware. "
            "Mock this method in tests."
        )


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
