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


@dataclass(frozen=True)
class RealtekLocalVersion:
    status: int
    hci_version: int
    hci_revision: int
    lmp_version: int
    manufacturer: int
    lmp_subversion: int


from pybluehost.transport.usb.base import USBTransport, parse_hci_reset_status
from pybluehost.transport.usb.intel import IntelUSBTransport


class RealtekUSBTransport(USBTransport):
    """Realtek Bluetooth USB transport with firmware loading.

    Realtek firmware loading sequence (based on Linux btrtl.c and Bumble):
    1. HCI_Reset → controller ready
    2. HCI_Read_Local_Version_Information → identify chip
    3. HCI_Realtek_Read_ROM_Version (vendor 0xFC6D) → rom_version
    4. Parse epatch firmware → select patch for (rom_version + 1)
    5. Download patch + optional config in ≤252-byte chunks (vendor cmd 0xFC20)
    6. HCI_Reset → activate firmware
    """

    # Realtek vendor command OCFs
    _RTK_READ_ROM_VERSION = 0x6D
    _RTK_DOWNLOAD_FW = 0x20

    # Epatch firmware format constants (from bumble/drivers/rtk.py)
    _RTK_EPATCH_SIGNATURE = b"Realtech"
    _RTK_EPATCH_V2_SIGNATURE = b"RTBTCore"
    _RTK_EXTENSION_SIGNATURE = bytes([0x51, 0x04, 0xFD, 0x77])
    _RTK_FRAGMENT_LENGTH = 252
    _RTK_PATCH_SNIPPETS = 0x01
    _RTK_PATCH_DUMMY_HEADER = 0x02
    _RTK_PATCH_SECURITY_HEADER = 0x03
    _HCI_READ_LOCAL_VERSION = (0x04 << 10) | 0x0001
    _RTK_USB_STOCK_FIRMWARE_TUPLES = {
        # Linux btrtl.c RTL8852B USB entry:
        # lmp_subver=0x8852, hci_rev=0x000b, hci_ver=0x0b.
        (0x8852, 0x000B, 0x0B),
        # Linux btrtl.c RTL8852C USB entry:
        # lmp_subver=0x8852, hci_rev=0x000c, hci_ver=0x0c.
        (0x8852, 0x000C, 0x0C),
    }

    async def _initialize(self) -> None:
        """Realtek 5-step firmware loading sequence."""
        logger.info("Realtek USBTransport initialized")
        reset_status = await self._try_initial_hci_reset()
        if reset_status == 0x00:
            logger.info("Realtek: initial HCI Reset status=0x00")
        elif reset_status is not None:
            raise RuntimeError(
                f"Realtek: initial HCI Reset status=0x{reset_status:02X}; "
                "refusing firmware download because controller state is not known"
            )
        else:
            raise RuntimeError(
                "Realtek: initial HCI Reset failed or returned no status; "
                "refusing firmware download because controller state is not known"
            )

        local_version_event = await self._read_local_version("pre-download")
        local_version = self._parse_local_version(local_version_event)
        logger.info(
            "Realtek: pre-download local version status=0x%02X hci=0x%02X rev=0x%04X lmp=0x%02X manufacturer=0x%04X subver=0x%04X",
            local_version.status,
            local_version.hci_version,
            local_version.hci_revision,
            local_version.lmp_version,
            local_version.manufacturer,
            local_version.lmp_subversion,
        )

        if not self._needs_firmware_download(local_version):
            logger.info("Realtek: firmware download not needed")
            return

        # Step 1: Read ROM Version
        rom_data = await self._send_realtek_vendor_cmd(self._RTK_READ_ROM_VERSION)
        rom_version = self._parse_rom_version(rom_data)
        logger.info("Realtek: ROM version=0x%02X", rom_version)

        # Step 4: Find firmware file
        fw_path = self._find_firmware()

        # Step 5: Parse epatch firmware and select correct patch
        fw_data = fw_path.read_bytes()
        payload = self._build_firmware_payload(fw_data, rom_version)
        await self._download_firmware_payload(payload)

        # Linux btrtl validates the loaded image by reading local version after
        # download. A final reset on this path can leave RTL8852C handles stale.
        await self._read_local_version_after_download()

    async def _try_initial_hci_reset(self) -> int | None:
        opcode = (0x03 << 10) | 0x03
        try:
            command = opcode.to_bytes(2, "little") + b"\x00"
            logger.info("Realtek: initial HCI Reset control write")
            await self._control_out(command)
            logger.info("Realtek: initial HCI Reset waiting for event")
            event = await self._wait_for_command_complete(opcode)
        except Exception as e:
            logger.warning("Realtek: initial HCI Reset command failed: %s: %s", type(e).__name__, e)
            return None
        return self._command_complete_status(event, opcode)

    async def _send_realtek_vendor_cmd(
        self, ocf: int, params: bytes = b""
    ) -> bytes:
        """Send Realtek vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        command = self._build_realtek_vendor_command(ocf, params)
        await self._control_out(command)
        return await self._wait_for_command_complete(opcode)

    def _build_realtek_vendor_command(self, ocf: int, params: bytes = b"") -> bytes:
        opcode = (0x3F << 10) | ocf
        opcode_bytes = opcode.to_bytes(2, "little")
        param_len = len(params).to_bytes(1, "little")
        return opcode_bytes + param_len + params

    def _parse_rom_version(self, event_data: bytes) -> int:
        """Extract ROM version from Realtek Read ROM Version response."""
        # Event: event_code(1) + param_len(1) + num_hci_cmds(1) +
        #        opcode(2) + status(1) + rom_version(1)
        if len(event_data) != 7:
            raise RuntimeError("Realtek: ROM version event length mismatch")
        return event_data[6]

    @classmethod
    def _parse_local_version(cls, event_data: bytes) -> RealtekLocalVersion:
        cls._validate_command_complete(event_data, cls._HCI_READ_LOCAL_VERSION)
        if len(event_data) != 14:
            raise RuntimeError("Realtek: local version event length mismatch")
        return RealtekLocalVersion(
            status=event_data[5],
            hci_version=event_data[6],
            hci_revision=int.from_bytes(event_data[7:9], "little"),
            lmp_version=event_data[9],
            manufacturer=int.from_bytes(event_data[10:12], "little"),
            lmp_subversion=int.from_bytes(event_data[12:14], "little"),
        )

    @staticmethod
    def _validate_command_complete(event: bytes, opcode: int) -> None:
        expected = opcode.to_bytes(2, "little")
        if len(event) < 6 or event[0] != 0x0E or event[3:5] != expected:
            raise RuntimeError(
                f"Realtek: expected Command Complete for 0x{opcode:04X}, got {event.hex(' ')}"
            )
        if event[5] != 0x00:
            raise RuntimeError(
                f"Realtek: command 0x{opcode:04X} failed with status 0x{event[5]:02X}"
            )

    @classmethod
    def _validate_download_response(cls, event: bytes, expected_index: int) -> None:
        cls._validate_command_complete(event, (0x3F << 10) | cls._RTK_DOWNLOAD_FW)
        if len(event) != 7:
            raise RuntimeError("Realtek: download firmware event length mismatch")
        if event[6] != expected_index:
            raise RuntimeError(
                f"Realtek: download index echo mismatch; expected 0x{expected_index:02X}, got 0x{event[6]:02X}"
            )

    async def _wait_for_command_complete(self, opcode: int, timeout: float = 5.0) -> bytes:
        """Wait for the Command Complete matching opcode, ignoring stale events."""
        deadline = asyncio.get_event_loop().time() + timeout
        last_event: bytes | None = None
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                detail = last_event.hex(" ") if last_event is not None else "none"
                raise TimeoutError(
                    f"Realtek: no Command Complete for 0x{opcode:04X}; last event={detail}"
                )
            event = await self._wait_for_event(timeout=remaining)
            last_event = event
            if len(event) >= 5 and event[0] == 0x0E:
                event_opcode = int.from_bytes(event[3:5], "little")
                if event_opcode == opcode:
                    self._validate_command_complete(event, opcode)
                    return event
                logger.warning(
                    "Realtek: ignoring stale Command Complete for 0x%04X while waiting for 0x%04X",
                    event_opcode,
                    opcode,
                )
                continue
            logger.warning(
                "Realtek: ignoring unexpected event while waiting for 0x%04X: %s",
                opcode,
                event.hex(" "),
            )

    def _needs_firmware_download(self, local_version: RealtekLocalVersion) -> bool:
        """Return True only for local-version tuples known to be stock ROM firmware."""
        if local_version.status != 0x00:
            raise RuntimeError(
                f"Realtek: Read Local Version failed with status 0x{local_version.status:02X}"
            )
        key = (
            local_version.lmp_subversion,
            local_version.hci_revision,
            local_version.hci_version,
        )
        if key in self._RTK_USB_STOCK_FIRMWARE_TUPLES:
            return True
        logger.info(
            "Realtek: local version tuple is not a known stock firmware tuple; assuming operational"
        )
        return False

    def _find_firmware(self) -> "Path":
        """Locate Realtek firmware file using FirmwareManager."""
        mgr = FirmwareManager(
            vendor="realtek",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        fw_name = self._chip_info.firmware_pattern if self._chip_info else "rtl_fw"
        for candidate in self._firmware_candidates(fw_name):
            try:
                return mgr.find(candidate)
            except Exception:
                continue
        return mgr.find(fw_name)

    @staticmethod
    def _firmware_candidates(fw_name: str) -> list[str]:
        """Return firmware names in preferred lookup order."""
        candidates: list[str] = []
        if fw_name == "rtl8852cu_fw.bin":
            candidates.append("rtl8852cu_fw_v2.bin")
        elif fw_name == "rtl8852cu_fw":
            candidates.extend(["rtl8852cu_fw_v2.bin", "rtl8852cu_fw.bin"])

        candidates.append(fw_name)
        if not fw_name.endswith(".bin"):
            candidates.append(f"{fw_name}.bin")
        return list(dict.fromkeys(candidates))

    @classmethod
    def _build_firmware_payload(
        cls, firmware: bytes, rom_version: int, key_id: int = 0
    ) -> bytes:
        """Build the Realtek download payload for the current ROM version."""
        if firmware.startswith(cls._RTK_EPATCH_V2_SIGNATURE):
            return cls._parse_epatch_v2_firmware(firmware, rom_version, key_id=key_id)
        if not firmware.startswith(cls._RTK_EPATCH_SIGNATURE):
            raise RuntimeError("Realtek: unsupported firmware format")

        version, patches = cls._parse_epatch_firmware(firmware)
        chip_id = rom_version + 1
        for patch_chip_id, patch in patches:
            if patch_chip_id == chip_id:
                return patch[:-4] + struct.pack("<I", version)
        raise RuntimeError(
            f"Realtek: no epatch entry for chip_id=0x{chip_id:04X}"
        )

    @classmethod
    def _parse_epatch_firmware(cls, firmware: bytes) -> tuple[int, list[tuple[int, bytes]]]:
        """Parse Realtek epatch firmware into selectable patch payloads."""
        if not firmware.endswith(cls._RTK_EXTENSION_SIGNATURE):
            raise RuntimeError("Realtek: epatch firmware missing extension signature")

        header_size = 14
        if len(firmware) < header_size:
            raise RuntimeError("Realtek: epatch firmware too short")

        version, patch_count = struct.unpack("<IH", firmware[8:14])
        tables_size = header_size + 8 * patch_count
        if tables_size > len(firmware):
            raise RuntimeError("Realtek: epatch tables exceed firmware size")

        chip_id_offset = header_size
        length_offset = chip_id_offset + 2 * patch_count
        patch_offset = chip_id_offset + 4 * patch_count
        patches: list[tuple[int, bytes]] = []

        for index in range(patch_count):
            chip_id = struct.unpack_from("<H", firmware, chip_id_offset + 2 * index)[0]
            patch_length = struct.unpack_from("<H", firmware, length_offset + 2 * index)[0]
            data_offset = struct.unpack_from("<I", firmware, patch_offset + 4 * index)[0]
            if data_offset + patch_length > len(firmware):
                raise RuntimeError("Realtek: epatch entry exceeds firmware size")
            patches.append((chip_id, firmware[data_offset : data_offset + patch_length]))

        return version, patches

    @classmethod
    def _parse_epatch_v2_firmware(
        cls, firmware: bytes, rom_version: int, key_id: int = 0
    ) -> bytes:
        """Parse Realtek RTBTCore firmware into the selected payload."""
        if not firmware.endswith(cls._RTK_EXTENSION_SIGNATURE):
            raise RuntimeError("Realtek: epatch v2 firmware missing extension signature")
        if len(firmware) < 20:
            raise RuntimeError("Realtek: epatch v2 firmware too short")

        target_eco = rom_version + 1
        section_count = struct.unpack_from("<I", firmware, 16)[0]
        pos = 20
        payloads: list[tuple[int, bytes]] = []
        data_end = len(firmware) - 7

        for _ in range(section_count):
            if pos + 8 > data_end:
                raise RuntimeError("Realtek: epatch v2 section header exceeds firmware size")
            opcode, section_len = struct.unpack_from("<II", firmware, pos)
            pos += 8
            section_end = pos + section_len
            if section_end > data_end:
                raise RuntimeError("Realtek: epatch v2 section exceeds firmware size")

            if opcode in (cls._RTK_PATCH_SNIPPETS, cls._RTK_PATCH_DUMMY_HEADER):
                payloads.extend(
                    cls._parse_epatch_v2_section(firmware[pos:section_end], target_eco)
                )
            elif opcode == cls._RTK_PATCH_SECURITY_HEADER:
                if key_id:
                    payloads.extend(
                        cls._parse_epatch_v2_section(
                            firmware[pos:section_end],
                            target_eco,
                            security_key_id=key_id,
                        )
                    )
            pos = section_end

        if not payloads:
            raise RuntimeError(f"Realtek: no epatch v2 entry for eco=0x{target_eco:02X}")

        payloads.sort(key=lambda item: item[0])
        return b"".join(payload for _, payload in payloads)

    @classmethod
    def _parse_epatch_v2_section(
        cls,
        section: bytes,
        target_eco: int,
        security_key_id: int | None = None,
    ) -> list[tuple[int, bytes]]:
        if len(section) < 4:
            raise RuntimeError("Realtek: epatch v2 section too short")
        subsection_count = struct.unpack_from("<H", section, 0)[0]
        pos = 4
        payloads: list[tuple[int, bytes]] = []

        for _ in range(subsection_count):
            if pos + 8 > len(section):
                raise RuntimeError("Realtek: epatch v2 subsection header exceeds section")
            eco = section[pos]
            prio = section[pos + 1]
            data_len = struct.unpack_from("<I", section, pos + 4)[0]
            data_start = pos + 8
            data_end = data_start + data_len
            if data_end > len(section):
                raise RuntimeError("Realtek: epatch v2 subsection exceeds section")
            if eco == target_eco and (
                security_key_id is None or section[pos + 2] == security_key_id
            ):
                payloads.append((prio, section[data_start:data_end]))
            pos = data_end

        return payloads

    async def _read_local_version(self, label: str) -> bytes:
        command = self._HCI_READ_LOCAL_VERSION.to_bytes(2, "little") + b"\x00"
        logger.info("Realtek: %s Read Local Version control write", label)
        await self._control_out(command)
        logger.info("Realtek: %s Read Local Version waiting for event", label)
        return await self._wait_for_command_complete(self._HCI_READ_LOCAL_VERSION)

    async def _read_local_version_after_download(self) -> bytes:
        event = await self._read_local_version("post-download")
        local_version = self._parse_local_version(event)
        logger.info(
            "Realtek: post-download local version status=0x%02X hci=0x%02X rev=0x%04X lmp=0x%02X manufacturer=0x%04X subver=0x%04X",
            local_version.status,
            local_version.hci_version,
            local_version.hci_revision,
            local_version.lmp_version,
            local_version.manufacturer,
            local_version.lmp_subversion,
        )
        return event

    async def _download_firmware_payload(self, payload: bytes) -> None:
        chunks = self._split_firmware(payload)
        next_index = 0
        for index, chunk in enumerate(chunks):
            # Match Linux btrtl exactly: j starts at 0, increments per fragment,
            # and is reset to 1 immediately after sending raw index 0x7F.
            download_index = next_index
            next_index += 1
            if download_index == 0x7F:
                next_index = 1
            if index == len(chunks) - 1:
                download_index |= 0x80
            if download_index > 0xFF:
                raise RuntimeError("Realtek: firmware payload has too many fragments")
            if index == 0 or index == len(chunks) - 1 or index % 32 == 0:
                logger.info(
                    "Realtek: downloading firmware fragment %d/%d index=0x%02X size=%d",
                    index + 1,
                    len(chunks),
                    download_index,
                    len(chunk),
                )
            params = bytes([download_index]) + chunk
            if index == len(chunks) - 1:
                await self._send_realtek_download_final(params)
            else:
                event = await self._send_realtek_vendor_cmd(self._RTK_DOWNLOAD_FW, params)
                self._validate_download_response(event, download_index)

    async def _send_realtek_download_final(self, params: bytes) -> None:
        """Send final firmware fragment.

        The final fragment changes controller state. Do not continue if its
        Command Complete is missing or malformed; sending follow-up commands
        after a bad finalization can leave USB hardware wedged until power cycle.
        """
        command = self._build_realtek_vendor_command(self._RTK_DOWNLOAD_FW, params)
        logger.info("Realtek: final firmware fragment control write")
        await self._control_out(command)
        logger.info("Realtek: final firmware fragment waiting for Command Complete")
        event = await self._wait_for_command_complete((0x3F << 10) | self._RTK_DOWNLOAD_FW)
        self._validate_download_response(event, params[0])

    @staticmethod
    def _split_firmware(data: bytes, chunk_size: int = 252) -> list[bytes]:
        """Split firmware binary into chunks of ≤chunk_size bytes."""
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    async def _wait_for_event(self, timeout: float = 5.0) -> bytes:
        """Wait for HCI event via interrupt IN, falling back to bulk IN."""
        loop = asyncio.get_event_loop()
        timeout_ms = int(timeout * 1000)
        last_error: Exception | None = None

        try:
            return await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, 50),
            )
        except Exception as e:
            last_error = e

        if hasattr(self, "_ep_bulk_in") and self._ep_bulk_in is not None:
            try:
                return await loop.run_in_executor(
                    None,
                    lambda: bytes(self._ep_bulk_in.read(1024, timeout=timeout_ms)),
                )
            except Exception as e:
                last_error = e

        try:
            return await loop.run_in_executor(
                None,
                lambda: self.read_interrupt_sync(255, timeout_ms),
            )
        except Exception as e:
            last_error = e

        if last_error is not None:
            raise last_error
        raise TimeoutError(
            f"No HCI event received within {timeout}s on either Interrupt or Bulk IN"
        )


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
