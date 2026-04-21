"""USB HCI transport: ChipInfo registry, USBTransport base, Intel/Realtek subclasses."""

from __future__ import annotations

import asyncio
import logging
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pybluehost.transport.base import Transport, TransportInfo
from pybluehost.transport.firmware import FirmwareManager, FirmwarePolicy

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
    def _get_usb_backend(cls) -> Any:
        """Return the best available pyusb backend for this platform.

        On Windows, prefers libusb-package (bundles libusb-1.0.dll).
        Falls back to pyusb default backend discovery on Linux/macOS.
        """
        if sys.platform == "win32":
            try:
                import libusb_package
                import usb.backend.libusb1
                be = usb.backend.libusb1.get_backend(
                    find_library=libusb_package.find_library
                )
                if be is not None:
                    return be
            except ImportError:
                pass
        return None  # pyusb default discovery

    @classmethod
    def auto_detect(
        cls,
        firmware_policy: FirmwarePolicy = FirmwarePolicy.PROMPT,
    ) -> "USBTransport":
        """Enumerate USB devices, match KNOWN_CHIPS, return correct subclass instance."""
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. Run: pip install pyusb"
            )

        backend = cls._get_usb_backend()
        # 1. Search known chips by VID/PID
        all_devices = list(usb.core.find(find_all=True, backend=backend))
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
                backend=backend,
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

        # Claim HCI interface 0 (HCI Commands/Events/ACL)
        import usb.util as usbutil
        try:
            self._device.set_configuration()
        except Exception:
            pass  # Already configured

        cfg = self._device.get_active_configuration()
        intf = cfg[(0, 0)]  # Interface 0, alternate setting 0

        # Locate Interrupt IN endpoint (HCI Events)
        self._ep_intr_in = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_INTR
            ),
        )
        # Locate Bulk IN/OUT endpoints (ACL Data)
        self._ep_bulk_in = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_IN
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
            ),
        )
        self._ep_bulk_out = usbutil.find_descriptor(
            intf,
            custom_match=lambda e: (
                usbutil.endpoint_direction(e.bEndpointAddress) == usbutil.ENDPOINT_OUT
                and usbutil.endpoint_type(e.bmAttributes) == usbutil.ENDPOINT_TYPE_BULK
            ),
        )

        # Event queue for _wait_for_event
        self._event_queue: asyncio.Queue[bytes] = asyncio.Queue()

        await self._initialize()
        self._is_open = True

    async def close(self) -> None:
        """Close USB transport: cancel readers, release interface."""
        for task in self._reader_tasks:
            task.cancel()
        self._reader_tasks.clear()
        try:
            import usb.util as usbutil
            usbutil.release_interface(self._device, 0)
        except Exception:
            pass
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
        """Send HCI command via USB control transfer (EP0, BT class request)."""
        # HCI Command via control transfer:
        # bmRequestType = 0x20 (Class | Interface | Host-to-Device)
        # bRequest      = 0x00
        # wValue        = 0x0000
        # wIndex        = 0x0000 (interface 0)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._device.ctrl_transfer(
                0x20,   # bmRequestType
                0x00,   # bRequest
                0x0000, # wValue
                0x0000, # wIndex
                data,
            ),
        )

    async def _bulk_out(self, data: bytes) -> None:
        """Send ACL data via USB bulk OUT endpoint."""
        if not hasattr(self, "_ep_bulk_out") or self._ep_bulk_out is None:
            raise RuntimeError("Bulk OUT endpoint not found (call open() first)")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._ep_bulk_out.write(data))

    async def _isoch_out(self, data: bytes) -> None:
        """Send SCO data via USB isochronous OUT endpoint.
        (Isochronous transfers not fully supported by libusb on Windows.)
        """
        raise NotImplementedError("Isochronous SCO transfers require OS-level access")

    def read_interrupt_sync(self, size: int = 64, timeout: int = 5000) -> bytes:
        """Blocking interrupt IN read (runs in executor thread)."""
        if not hasattr(self, "_ep_intr_in") or self._ep_intr_in is None:
            raise RuntimeError("Interrupt IN endpoint not found (call open() first)")
        data = self._ep_intr_in.read(size, timeout=timeout)
        return bytes(data)

    async def read_interrupt(self, size: int = 64, timeout: float = 5.0) -> bytes:
        """Async wrapper around interrupt IN read."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.read_interrupt_sync(size, int(timeout * 1000)),
        )

    def _verify_winusb_driver(self) -> None:
        """Windows: check device is bound to WinUSB, not Microsoft Bluetooth driver.

        On Windows, Intel BT devices bound to WinUSB are accessible via pyusb.
        If the device is still on bthusb.sys, pyusb will get Access Denied.
        We rely on pyusb raising USBError at open() time to surface this.
        """


class IntelUSBTransport(USBTransport):
    """Intel Bluetooth USB transport with firmware loading.

    Supports two protocols:
    - **Legacy** (hw_variant < 0x17): AX200, AX201, AC9560, AC8265, etc.
      Fixed-format Read Version, Enter Mfg Mode, Write Patch, Reset.
    - **New-gen** (hw_variant >= 0x17): AX210, AX211, BE200, etc.
      TLV-based Read Version V2, Secure Send firmware download, Reset with boot_param.
    """

    # Intel vendor command OCFs
    _INTEL_READ_VERSION = 0x05    # Read Version (legacy: no params; new-gen: param 0xFF)
    _INTEL_RESET = 0x01           # Intel Reset
    _INTEL_ENTER_MFG = 0x11      # Enter Manufacturer Mode (legacy only)
    _INTEL_SECURE_SEND = 0x09    # Secure Send (firmware download chunks)
    _INTEL_READ_BOOT_PARAMS = 0x0D  # Read Boot Params (legacy only)

    # Legacy firmware variant codes
    _FW_VARIANT_OPERATIONAL = 0x03
    _FW_VARIANT_BOOTLOADER = 0x06
    _FW_VARIANT_OPERATIONAL_NEW = 0x89   # operational on new platforms

    # Platform detection
    _HW_VARIANT_NEW_PLATFORM_MIN = 0x17  # hw_variant >= this → new-gen

    # New-gen image types (from TLV field 0x1C)
    _IMAGE_TYPE_BOOTLOADER = 0x01
    _IMAGE_TYPE_OPERATIONAL = 0x03

    # TLV type codes for new-gen Read Version V2
    _TLV_CNVI_TOP = 0x10
    _TLV_CNVR_TOP = 0x11
    _TLV_CNVI_BT = 0x12
    _TLV_DEV_REV_ID = 0x16
    _TLV_USB_VENDOR_ID = 0x17
    _TLV_USB_PRODUCT_ID = 0x18
    _TLV_IMAGE_TYPE = 0x1C
    _TLV_TIME_STAMP = 0x1D
    _TLV_BUILD_TYPE = 0x1E
    _TLV_BUILD_NUM = 0x1F
    _TLV_SECURE_BOOT = 0x27
    _TLV_OTP_LOCK = 0x28
    _TLV_API_LOCK = 0x29
    _TLV_DEBUG_LOCK = 0x2A
    _TLV_MIN_FW = 0x2B
    _TLV_FW_BUILD = 0x2D
    _TLV_SBE_TYPE = 0x2F       # SecureBootEngineType: 0x00=RSA, 0x01=ECDSA
    _TLV_OTP_BDADDR = 0x30
    _TLV_UNLOCKED_STATE = 0x31

    # Secure Boot Engine types
    _SBE_RSA = 0x00
    _SBE_ECDSA = 0x01

    # Boot params per engine type (from Bumble / Linux kernel)
    # BootParams(css_offset, css_size, pki_offset, pki_size,
    #            sig_offset, sig_size, write_offset)
    @dataclass(frozen=True)
    class _BootParams:
        css_offset: int
        css_size: int
        pki_offset: int
        pki_size: int
        sig_offset: int
        sig_size: int
        write_offset: int

    _BOOT_PARAMS_RSA = _BootParams(0, 128, 128, 256, 388, 256, 964)
    _BOOT_PARAMS_ECDSA = _BootParams(644, 128, 772, 96, 868, 96, 964)

    async def _initialize(self) -> None:
        """Intel firmware loading — auto-detects legacy vs new-gen platform.

        Tries V2 (TLV) Read Version first. If it succeeds with status 0x00 and
        returns TLV data, routes to the new-gen path. Otherwise falls back to
        the legacy fixed-format protocol.
        """
        # Try V2 Read Version (new-gen: 0xFC05 with param 0xFF)
        try:
            v2_data = await self._send_intel_vendor_cmd(
                self._INTEL_READ_VERSION, b"\xff"
            )
            v2_status = v2_data[5] if len(v2_data) > 5 else 0xFF
        except Exception:
            v2_status = 0xFF
            v2_data = b""

        if v2_status == 0x00 and len(v2_data) > 10:
            # New-gen platform: TLV response
            tlv = self._parse_tlv(v2_data[6:])
            logger.info("Intel new-gen platform detected (TLV response)")
            await self._initialize_newgen(tlv)
        else:
            # Legacy platform: fixed-format
            version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
            hw_variant = self._parse_hw_variant(version_data)
            fw_variant = self._parse_fw_variant(version_data)
            logger.info(
                "Intel legacy platform: hw_variant=0x%02X fw_variant=0x%02X",
                hw_variant, fw_variant,
            )
            await self._initialize_legacy(hw_variant, fw_variant, version_data)

    # ── New-gen initialization (BE200, AX210, AX211, etc.) ──────────────

    async def _initialize_newgen(self, tlv: dict[int, bytes]) -> None:
        """New-gen (TLV) firmware loading sequence (Bumble-compatible).

        1. Parse TLV: image_type, sbe_type, cnvi/cnvr
        2. If operational → done
        3. If bootloader → determine boot params (RSA/ECDSA),
           send CSS + PKI + Signature + payload, reset
        """
        image_type = tlv.get(self._TLV_IMAGE_TYPE, b"\xff")[0]
        cnvi_top = int.from_bytes(tlv.get(self._TLV_CNVI_TOP, b"\0\0\0\0")[:4], "little")
        cnvr_top = int.from_bytes(tlv.get(self._TLV_CNVR_TOP, b"\0\0\0\0")[:4], "little")
        sbe_type = tlv.get(self._TLV_SBE_TYPE, b"\x00")[0]
        otp_bdaddr = tlv.get(self._TLV_OTP_BDADDR, b"")

        logger.info(
            "Intel TLV: image_type=0x%02X sbe_type=0x%02X "
            "cnvi_top=0x%08X cnvr_top=0x%08X bdaddr=%s",
            image_type, sbe_type, cnvi_top, cnvr_top,
            otp_bdaddr.hex(":") if otp_bdaddr else "N/A",
        )

        if image_type == self._IMAGE_TYPE_OPERATIONAL:
            logger.info("Intel: firmware already operational, skipping load")
            return

        if image_type != self._IMAGE_TYPE_BOOTLOADER:
            raise RuntimeError(
                f"Intel: unexpected image_type=0x{image_type:02X} "
                f"(expected 0x01=bootloader or 0x03=operational)"
            )

        # Select boot params based on Secure Boot Engine type
        if sbe_type == self._SBE_ECDSA:
            bp = self._BOOT_PARAMS_ECDSA
            logger.info("Intel: ECDSA secure boot engine")
        else:
            bp = self._BOOT_PARAMS_RSA
            logger.info("Intel: RSA secure boot engine")

        # Compute firmware filename
        fw_basename = self._compute_fw_name(cnvi_top, cnvr_top)
        logger.info("Intel: bootloader mode — firmware needed: %s.sfi", fw_basename)

        # Find and load firmware
        fw_path = self._find_firmware_by_name(f"{fw_basename}.sfi")
        fw_data = fw_path.read_bytes()
        logger.info("Intel: firmware file %s (%d bytes)", fw_path.name, len(fw_data))

        if len(fw_data) < bp.write_offset:
            raise RuntimeError(
                f"Intel: firmware too small ({len(fw_data)} bytes, "
                f"need at least {bp.write_offset})"
            )

        # Download firmware via secure_send
        boot_address = await self._secure_send_firmware(fw_data, bp)
        logger.info("Intel: firmware download complete, boot_address=0x%08X", boot_address)

        # Wait for firmware_load_complete vendor event (type=0x06)
        logger.info("Intel: waiting for firmware load complete event...")
        await self._wait_for_vendor_event(expected_type=0x06, timeout=10.0)
        logger.info("Intel: firmware load complete")

        # Send Intel Reset with boot_address
        await self._intel_reset_newgen(boot_address)

        # Wait for boot complete vendor event (type=0x02)
        logger.info("Intel: waiting for boot complete event...")
        await self._wait_for_vendor_event(expected_type=0x02, timeout=10.0)
        logger.info("Intel: boot complete — device is now operational")

    async def _secure_send_firmware(
        self, fw_data: bytes, bp: _BootParams
    ) -> int:
        """Download firmware via Intel Secure Send (0xFC09).

        Uses BootParams to determine offsets for CSS/PKI/Signature/payload,
        which differ between RSA and ECDSA secure boot engines.

        Returns:
            boot_address: 32-bit boot address for Intel Reset.
        """
        # 1. Send CSS header (type=0x00)
        css = fw_data[bp.css_offset:bp.css_offset + bp.css_size]
        logger.info(
            "Intel: sending CSS header (type=0x00, offset=%d, %dB)",
            bp.css_offset, bp.css_size,
        )
        await self._secure_send(0x00, css)

        # 2. Send PKI key (type=0x03)
        pki = fw_data[bp.pki_offset:bp.pki_offset + bp.pki_size]
        logger.info(
            "Intel: sending PKI (type=0x03, offset=%d, %dB)",
            bp.pki_offset, bp.pki_size,
        )
        await self._secure_send(0x03, pki)

        # 3. Send Signature (type=0x02)
        sig = fw_data[bp.sig_offset:bp.sig_offset + bp.sig_size]
        logger.info(
            "Intel: sending Signature (type=0x02, offset=%d, %dB)",
            bp.sig_offset, bp.sig_size,
        )
        await self._secure_send(0x02, sig)

        # 4. Send firmware payload (type=0x01), 4-byte aligned HCI command chunks
        boot_address = 0
        offset = bp.write_offset
        frag_size = 0
        total_sent = 0

        while offset + frag_size + 3 <= len(fw_data):
            cmd_opcode = int.from_bytes(
                fw_data[offset + frag_size:offset + frag_size + 2], "little"
            )
            cmd_plen = fw_data[offset + frag_size + 2]

            # Check for boot_address command (0xFC0E)
            if cmd_opcode == 0xFC0E and offset + frag_size + 7 <= len(fw_data):
                boot_address = int.from_bytes(
                    fw_data[offset + frag_size + 3:offset + frag_size + 7], "little"
                )
                logger.info(
                    "Intel: found boot_address=0x%08X at offset %d",
                    boot_address, offset + frag_size,
                )

            frag_size += 3 + cmd_plen

            # Send when fragment is 4-byte aligned
            if frag_size % 4 == 0:
                await self._secure_send(0x01, fw_data[offset:offset + frag_size])
                total_sent += frag_size
                offset += frag_size
                frag_size = 0

        # Send any remaining data
        if frag_size > 0:
            await self._secure_send(0x01, fw_data[offset:offset + frag_size])
            total_sent += frag_size

        logger.info("Intel: payload sent (%d bytes total)", total_sent)
        return boot_address

    async def _secure_send(self, fragment_type: int, data: bytes) -> None:
        """Send data via Intel Secure Send (vendor 0xFC09), chunking at 252 bytes.

        Args:
            fragment_type: 0x00=CSS header, 0x01=data, 0x03=PKCS key
            data: Payload (chunked internally at 252-byte boundaries).
        """
        total = (len(data) + 251) // 252
        for i in range(0, len(data), 252):
            chunk = data[i:i + 252]
            params = bytes([fragment_type]) + chunk
            await self._send_intel_vendor_cmd(self._INTEL_SECURE_SEND, params)
            chunk_num = i // 252 + 1
            if chunk_num % 100 == 0 or chunk_num == total:
                logger.debug("Intel: secure_send type=%d chunk %d/%d", fragment_type, chunk_num, total)

    async def _wait_for_vendor_event(
        self, expected_type: int, timeout: float = 10.0
    ) -> bytes:
        """Wait for an Intel Vendor Specific Event (0xFF) with expected sub-type.

        Intel bootloader sends vendor events for:
        - type=0x02: boot complete
        - type=0x06: firmware download complete

        Events may arrive on either Interrupt IN or Bulk IN endpoint.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Intel: vendor event type=0x{expected_type:02X} "
                    f"not received within {timeout}s"
                )
            try:
                event = await self._wait_for_event(timeout=min(remaining, 2.0))
            except (TimeoutError, Exception):
                continue

            if len(event) >= 3 and event[0] == 0xFF:
                event_type = event[2]
                logger.debug("Intel: vendor event type=0x%02X", event_type)
                if event_type == expected_type:
                    return event
            elif len(event) >= 1 and event[0] == 0x0E:
                # Command Complete — might be a leftover, skip
                logger.debug("Intel: skipping Command Complete during vendor event wait")

    async def _intel_reset_newgen(self, boot_address: int) -> None:
        """Send Intel Reset (0xFC01) with boot_address for new-gen platforms.

        The reset command is fire-and-forget (no Command Complete expected).
        The device will reboot and send a vendor event (type=0x02) when ready.
        """
        params = struct.pack("<BBBBI", 0x00, 0x01, 0x00, 0x01, boot_address)
        opcode = (0x3F << 10) | self._INTEL_RESET
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        logger.info("Intel: reset command sent (boot_address=0x%08X)", boot_address)

    @staticmethod
    def _compute_fw_name(cnvi_top: int, cnvr_top: int) -> str:
        """Compute firmware basename from cnvi_top and cnvr_top values.

        Algorithm (from Linux kernel v6.12 btintel.h):
          INTEL_CNVX_TOP_TYPE(val)  = val & 0x00000FFF
          INTEL_CNVX_TOP_STEP(val)  = (val & 0x0F000000) >> 24
          INTEL_CNVX_TOP_PACK_SWAB(t, s) = __swab16((t) << 4 | s)

        Example: BE200 cnvi_top=0x02001910 → TYPE=0x910, STEP=2 → packed=0x0291
                 Firmware: ibt-0291-0291.sfi
        """
        def pack(val: int) -> int:
            t = val & 0x00000FFF          # bottom 12 bits
            s = (val & 0x0F000000) >> 24  # bits 24-27
            v = (t << 4) | s
            return ((v >> 8) & 0xFF) | ((v & 0xFF) << 8)  # swab16

        return f"ibt-{pack(cnvi_top):04x}-{pack(cnvr_top):04x}"

    @staticmethod
    def _parse_tlv(data: bytes) -> dict[int, bytes]:
        """Parse TLV (Type-Length-Value) entries from Intel Read Version V2 response."""
        tlv: dict[int, bytes] = {}
        pos = 0
        while pos + 2 <= len(data):
            tlv_type = data[pos]
            tlv_len = data[pos + 1]
            if pos + 2 + tlv_len > len(data):
                break
            tlv[tlv_type] = data[pos + 2 : pos + 2 + tlv_len]
            pos += 2 + tlv_len
        return tlv

    # ── Legacy initialization (AX200, AX201, AC9560, AC8265, etc.) ─────

    async def _initialize_legacy(
        self, hw_variant: int, fw_variant: int, version_data: bytes
    ) -> None:
        """Legacy firmware loading sequence.

        1. Check if already operational → skip
        2. Find firmware file
        3. Enter Manufacturer Mode (0xFC11)
        4. Stream firmware in ≤252-byte chunks via 0xFC09
        5. Intel Reset (0xFC01)
        6. Re-read version to verify
        """
        if self._is_operational(hw_variant, fw_variant):
            logger.info("Intel legacy: already operational, skipping")
            return

        logger.info("Intel legacy: bootloader mode, loading firmware")

        # Find firmware
        fw_path = self._find_firmware()
        fw_data = fw_path.read_bytes()

        # Enter Manufacturer Mode
        await self._send_intel_vendor_cmd(self._INTEL_ENTER_MFG)

        # Stream firmware in chunks
        for chunk in self._split_firmware(fw_data):
            await self._send_intel_vendor_cmd(self._INTEL_SECURE_SEND, chunk)

        # Intel Reset
        await self._send_intel_vendor_cmd(self._INTEL_RESET)

        # Verify
        version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
        fw_variant = self._parse_fw_variant(version_data)
        if not self._is_operational(hw_variant, fw_variant):
            raise RuntimeError(
                f"Intel firmware load failed: fw_variant=0x{fw_variant:02X}, "
                f"expected operational variant for hw_variant=0x{hw_variant:02X}"
            )

    # ── Shared helpers ──────────────────────────────────────────────────

    async def _send_intel_vendor_cmd(
        self, ocf: int, params: bytes = b""
    ) -> bytes:
        """Send Intel vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        command = opcode_bytes + param_len + params
        await self._control_out(command)
        return await self._wait_for_event()

    def _parse_fw_variant(self, event_data: bytes) -> int:
        """Extract fw_variant from legacy HCI_Intel_Read_Version response.

        Response layout (Command Complete, 0x0E):
          [0]  event_code
          [1]  param_total_len
          [2]  num_hci_cmds
          [3,4] opcode (little-endian)
          [5]  status
          [6]  hw_platform
          [7]  hw_variant
          [8]  hw_revision
          [9]  fw_variant
        """
        if len(event_data) >= 10:
            return event_data[9]
        return 0xFF

    def _parse_hw_variant(self, event_data: bytes) -> int:
        """Extract hw_variant from legacy HCI_Intel_Read_Version response at [7]."""
        if len(event_data) >= 8:
            return event_data[7]
        return 0xFF

    def _is_operational(self, hw_variant: int, fw_variant: int) -> bool:
        """Return True if device is operational (legacy protocol)."""
        if hw_variant >= self._HW_VARIANT_NEW_PLATFORM_MIN:
            return fw_variant == self._FW_VARIANT_OPERATIONAL_NEW
        return fw_variant == self._FW_VARIANT_OPERATIONAL

    def _find_firmware(self) -> Path:
        """Locate Intel firmware file using FirmwareManager (legacy: glob pattern)."""
        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        pattern = self._chip_info.firmware_pattern if self._chip_info else "ibt-*"
        for search_dir in mgr._search_dirs():
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return matches[0]
        return mgr.find(pattern)

    def _find_firmware_by_name(self, filename: str) -> Path:
        """Locate firmware file by exact name (new-gen: computed from TLV)."""
        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        return mgr.find(filename)

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event from either Interrupt IN or Bulk IN endpoint.

        Intel bootloaders deliver Command Complete events via the Bulk IN
        endpoint during firmware download. We try interrupt first with a very
        short timeout (50ms), then bulk IN for the remaining time.
        """
        loop = asyncio.get_event_loop()
        timeout_ms = int(timeout * 1000)

        # Quick check on interrupt IN (standard HCI event path, 50ms)
        try:
            data = await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, 50),
            )
            return data
        except Exception:
            pass

        # Then try bulk IN (Intel bootloader firmware loading path)
        if hasattr(self, "_ep_bulk_in") and self._ep_bulk_in is not None:
            try:
                data = await loop.run_in_executor(
                    None,
                    lambda: bytes(self._ep_bulk_in.read(1024, timeout=timeout_ms)),
                )
                return data
            except Exception:
                pass

        # Final attempt: interrupt IN with full timeout
        try:
            data = await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, timeout_ms),
            )
            return data
        except Exception:
            pass

        raise TimeoutError(
            f"No HCI event received within {timeout}s on either Interrupt or Bulk IN"
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
        """Wait for HCI event via interrupt IN endpoint."""
        return await self.read_interrupt(size=64, timeout=timeout)


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
    ChipInfo("realtek", "RTL8761B", 0x0BDA, 0x8771, "rtl8761b_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852AE", 0x0BDA, 0x2852, "rtl8852au_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852BE", 0x0BDA, 0x887B, "rtl8852bu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8852CE", 0x0BDA, 0x4853, "rtl8852cu_fw", RealtekUSBTransport),
    ChipInfo("realtek", "RTL8723DE", 0x0BDA, 0xB009, "rtl8723d_fw", RealtekUSBTransport),
]
