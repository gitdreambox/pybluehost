"""IntelUSBTransport — initializes Intel Bluetooth chips (AX2xx series, BE200, etc).

Implements the 6-step Intel firmware upload sequence: Read Version → Enter
Manufacturer Mode (legacy) → Secure Send firmware chunks → Reset → verify.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import struct
from dataclasses import dataclass
from pathlib import Path

from pybluehost.transport.firmware import FirmwareManager
from pybluehost.transport.usb.base import USBTransport

logger = logging.getLogger(__name__)


# USB Alt Setting by SCO codec — mirrors btusb.c BTUSB_ISOC_ALT_BAND_NB/WB constants.
# Verified against AX200 / AX210 / BE200; other Intel chips use the same mapping.
INTEL_SCO_ALT_BY_CODEC: dict[str, int] = {
    "CVSD": 1,   # narrow-band, 8 kHz mono, BTUSB_ISOC_ALT_BAND_NB
    "mSBC": 6,   # wide-band, 16 kHz mono, BTUSB_ISOC_ALT_BAND_WB
}


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
    _FW_VARIANT_OPERATIONAL_LEGACY_FW = 0x23
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
    _BOOT_PARAMS_LEGACY_RSA = _BootParams(0, 128, 128, 256, 388, 256, 644)
    _BOOT_PARAMS_ECDSA = _BootParams(644, 128, 772, 96, 868, 96, 964)

    async def prepare_for_sco(self, codec: str) -> None:
        """Intel-specific: select USB Alt Setting based on codec.

        BlueZ btusb.c uses Alt 1 for CVSD (narrow-band) and Alt 6 for mSBC
        (wide-band) on Intel chips. The exact alt numbers may differ on
        other vendors; this mapping is verified against AX200 / AX210 / BE200.
        """
        alt = INTEL_SCO_ALT_BY_CODEC.get(codec)
        if alt is None:
            raise ValueError(
                f"Intel: unsupported SCO codec {codec!r} "
                f"(known: {sorted(INTEL_SCO_ALT_BY_CODEC)})"
            )
        await self.select_sco_alt_setting(alt)

    async def _initialize(self) -> None:
        """Intel firmware loading — auto-detects legacy vs new-gen platform.

        Tries V2 (TLV) Read Version first. If it succeeds with status 0x00 and
        returns TLV data, routes to the new-gen path. Otherwise falls back to
        the legacy fixed-format protocol.
        """
        logger.info("Intel USBTransport initialized")
        reset_status = await self._try_initial_hci_reset()
        if reset_status == 0x00:
            logger.info("Intel: initial HCI Reset status=0x00")
        elif reset_status is not None:
            logger.warning(
                "Intel: initial HCI Reset status=0x%02X; firmware recovery may be required",
                reset_status,
            )
        else:
            logger.warning("Intel: initial HCI Reset failed or returned no status")

        # Try V2 Read Version (new-gen: 0xFC05 with param 0xFF)
        try:
            v2_data = await self._send_intel_vendor_cmd(
                self._INTEL_READ_VERSION, b"\xff"
            )
            v2_status = v2_data[5] if len(v2_data) > 5 else 0xFF
        except Exception:
            v2_status = 0xFF
            v2_data = b""

        tlv = self._parse_tlv(v2_data[6:]) if v2_status == 0x00 and len(v2_data) > 10 else {}
        if self._has_newgen_tlv(tlv):
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

    async def _try_initial_hci_reset(self) -> int | None:
        try:
            event = await self._send_hci_reset()
        except Exception as e:
            logger.warning("Intel: initial HCI Reset command failed: %s: %s", type(e).__name__, e)
            return None
        return self._command_complete_status(event, (0x03 << 10) | 0x03)

    # ── New-gen initialization (BE200, AX210, AX211, etc.) ──────────────

    async def _initialize_newgen(self, tlv: dict[int, bytes]) -> None:
        """New-gen (TLV) firmware loading sequence (Bumble-compatible).

        1. Parse TLV: image_type, sbe_type, cnvi/cnvr
        2. If operational → done
        3. If bootloader → determine boot params (RSA/ECDSA),
           send CSS + PKI + Signature + payload, reset
        """
        self._validate_newgen_tlv(tlv)
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
                f"(expected 0x01=bootloader or 0x03=operational). "
                f"Parsed TLV keys: {self._format_tlv_keys(tlv)}. "
                "The controller may be in a failed firmware recovery state; "
                "power-cycle/replug the adapter and run `pybluehost tools usb diagnose`."
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
        payload_total = len(fw_data) - bp.write_offset
        payload_fragments: list[tuple[int, bytes, int]] = []

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
                payload_fragments.append(
                    (offset, fw_data[offset:offset + frag_size], total_sent)
                )
                total_sent += frag_size
                offset += frag_size
                frag_size = 0

        # Send any remaining data
        if frag_size > 0:
            payload_fragments.append(
                (offset, fw_data[offset:offset + frag_size], total_sent)
            )
            total_sent += frag_size

        await self._secure_send_payload(payload_fragments, payload_total=payload_total)
        logger.info("Intel: payload sent (%d bytes total)", total_sent)
        return boot_address

    async def _secure_send_payload(
        self,
        fragments: list[tuple[int, bytes, int]],
        *,
        payload_total: int,
    ) -> None:
        commands: list[tuple[bytes, str]] = []
        progress_by_command_index: dict[int, int] = {}
        last_progress_log = 0
        for offset, data, total_sent in fragments:
            self._append_secure_send_commands(
                commands,
                0x01,
                data,
                context=(
                    f"payload offset={offset} size={len(data)} "
                    f"sent={total_sent}/{payload_total}"
                ),
                base_offset=offset,
            )
            progress = total_sent + len(data)
            if (
                last_progress_log == 0
                or progress - last_progress_log >= 64 * 1024
                or progress == payload_total
            ):
                progress_by_command_index[len(commands) - 1] = progress
                last_progress_log = progress
        await self._send_intel_secure_send_commands(
            commands,
            progress_by_command_index=progress_by_command_index,
            progress_total=payload_total,
        )

    async def _secure_send(
        self,
        fragment_type: int,
        data: bytes,
        *,
        context: str | None = None,
        base_offset: int | None = None,
    ) -> None:
        """Send data via Intel Secure Send (vendor 0xFC09), chunking at 252 bytes.

        Args:
            fragment_type: 0x00=CSS header, 0x01=data, 0x03=PKCS key
            data: Payload (chunked internally at 252-byte boundaries).
        """
        commands: list[tuple[bytes, str]] = []
        self._append_secure_send_commands(
            commands,
            fragment_type,
            data,
            context=context,
            base_offset=base_offset,
        )
        await self._send_intel_secure_send_commands(commands)

    def _append_secure_send_commands(
        self,
        commands: list[tuple[bytes, str]],
        fragment_type: int,
        data: bytes,
        *,
        context: str | None = None,
        base_offset: int | None = None,
    ) -> None:
        total = (len(data) + 251) // 252
        for i in range(0, len(data), 252):
            chunk = data[i:i + 252]
            params = bytes([fragment_type]) + chunk
            chunk_num = i // 252 + 1
            chunk_context = (
                f"secure_send type={fragment_type} chunk={chunk_num}/{total} "
                f"len={len(chunk)}"
            )
            if base_offset is not None:
                chunk_context += f" offset={base_offset + i}"
            if context:
                chunk_context = f"{context}; {chunk_context}"
            commands.append(
                (
                    self._build_intel_vendor_command(
                        self._INTEL_SECURE_SEND, params
                    ),
                    chunk_context,
                )
            )
            logger.debug(
                "Intel: secure_send type=%d chunk %d/%d", fragment_type, chunk_num, total
            )

    async def _send_intel_secure_send_commands(
        self,
        commands: list[tuple[bytes, str]],
        *,
        progress_by_command_index: dict[int, int] | None = None,
        progress_total: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        if not commands:
            return

        max_in_flight = 1
        next_command = 0
        pending_contexts: collections.deque[str] = collections.deque()

        while next_command < len(commands) or pending_contexts:
            while next_command < len(commands) and len(pending_contexts) < max_in_flight:
                command_index = next_command
                command, context = commands[next_command]
                logger.debug(
                    "Intel: vendor cmd 0xFC09 (%s) send in_flight=%d/%d",
                    context, len(pending_contexts) + 1, max_in_flight,
                )
                await self._control_out(command)
                if (
                    progress_by_command_index is not None
                    and progress_total is not None
                    and command_index in progress_by_command_index
                ):
                    logger.info(
                        "Intel: payload progress: %d/%d bytes",
                        progress_by_command_index[command_index],
                        progress_total,
                    )
                pending_contexts.append(context)
                next_command += 1

            if not pending_contexts:
                continue

            event = await self._wait_for_intel_firmware_command_complete(
                pending_contexts[0],
                timeout=timeout,
            )
            pending_contexts.popleft()
            num_packets = self._parse_command_complete_num_packets(
                event,
                expected_opcode=(0x3F << 10) | self._INTEL_SECURE_SEND,
            )
            if num_packets > 0:
                max_in_flight = max(1, num_packets)

    async def _wait_for_intel_firmware_command_complete(
        self,
        context: str,
        *,
        timeout: float = 5.0,
    ) -> bytes:
        label = f"vendor cmd 0xFC09 ({context})"
        while True:
            try:
                event = await self._wait_for_event_bulk_first(timeout=timeout)
            except TimeoutError:
                logger.info("Intel: %s timeout after %gs", label, timeout)
                raise
            except asyncio.CancelledError:
                logger.info("Intel: %s cancelled while waiting for Command Complete", label)
                raise

            if len(event) >= 3 and event[0] == 0xFF:
                self._defer_intel_vendor_event(event)
                continue
            break

        status = self._parse_command_complete_status(
            event,
            expected_opcode=(0x3F << 10) | self._INTEL_SECURE_SEND,
        )
        if status != 0:
            raise RuntimeError(f"Intel: {label} failed with status 0x{status:02X}")
        return event

    def _defer_intel_vendor_event(self, event: bytes) -> None:
        if not hasattr(self, "_deferred_intel_vendor_events"):
            self._deferred_intel_vendor_events: collections.deque[bytes] = (
                collections.deque()
            )
        self._deferred_intel_vendor_events.append(event)

    async def _wait_for_event_bulk_first(self, timeout: float = 5.0) -> bytes:
        if not hasattr(self, "_ep_bulk_in") or self._ep_bulk_in is None:
            return await self._wait_for_event(timeout=timeout)

        loop = asyncio.get_event_loop()
        timeout_ms = int(timeout * 1000)
        try:
            return await loop.run_in_executor(
                None,
                lambda: bytes(self._ep_bulk_in.read(1024, timeout=timeout_ms)),
            )
        except Exception:
            return await self._wait_for_event(timeout=timeout)

    @staticmethod
    def _parse_command_complete_num_packets(
        event: bytes,
        *,
        expected_opcode: int,
    ) -> int:
        if len(event) < 6 or event[0] != 0x0E:
            raise RuntimeError(f"Intel: expected Command Complete, got {event.hex(' ')}")
        opcode = int.from_bytes(event[3:5], "little")
        if opcode != expected_opcode:
            raise RuntimeError(
                "Intel: unexpected Command Complete opcode "
                f"0x{opcode:04X}, expected 0x{expected_opcode:04X}"
            )
        return event[2]

    @classmethod
    def _parse_command_complete_status(
        cls,
        event: bytes,
        *,
        expected_opcode: int,
    ) -> int:
        cls._parse_command_complete_num_packets(
            event,
            expected_opcode=expected_opcode,
        )
        return event[5]

    async def _wait_for_vendor_event(
        self, expected_type: int, timeout: float = 10.0
    ) -> bytes:
        """Wait for an Intel Vendor Specific Event (0xFF) with expected sub-type.

        Intel bootloader sends vendor events for:
        - type=0x02: boot complete
        - type=0x06: firmware download complete

        Events may arrive on either Interrupt IN or Bulk IN endpoint.
        """
        logger.info(
            "Intel: vendor event type=0x%02X wait start timeout=%gs",
            expected_type, timeout,
        )
        deferred_events = getattr(self, "_deferred_intel_vendor_events", None)
        if deferred_events is not None:
            for _ in range(len(deferred_events)):
                event = deferred_events.popleft()
                if len(event) >= 3 and event[0] == 0xFF and event[2] == expected_type:
                    return event
                deferred_events.append(event)

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info(
                    "Intel: vendor event type=0x%02X wait timeout after %gs",
                    expected_type, timeout,
                )
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

    @classmethod
    def _validate_newgen_tlv(cls, tlv: dict[int, bytes]) -> None:
        required = {
            cls._TLV_CNVI_TOP: "CNVI_TOP",
            cls._TLV_CNVR_TOP: "CNVR_TOP",
            cls._TLV_IMAGE_TYPE: "IMAGE_TYPE",
        }
        missing = [
            f"0x{field:02X}({name})"
            for field, name in required.items()
            if len(tlv.get(field, b"")) == 0
        ]
        if missing:
            raise RuntimeError(
                "Intel: Read Version V2 returned an invalid TLV response; "
                f"missing required TLV fields: {', '.join(missing)}. "
                f"Parsed TLV keys: {cls._format_tlv_keys(tlv)}. "
                "The controller may be in a failed firmware recovery state; "
                "power-cycle/replug the adapter and run `pybluehost tools usb diagnose`."
            )

    @classmethod
    def _has_newgen_tlv(cls, tlv: dict[int, bytes]) -> bool:
        return (
            len(tlv.get(cls._TLV_CNVI_TOP, b"")) > 0
            and len(tlv.get(cls._TLV_CNVR_TOP, b"")) > 0
            and len(tlv.get(cls._TLV_IMAGE_TYPE, b"")) > 0
        )

    @staticmethod
    def _format_tlv_keys(tlv: dict[int, bytes]) -> str:
        if not tlv:
            return "none"
        return ", ".join(f"0x{key:02X}" for key in sorted(tlv))

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
        fw_path = self._find_firmware(version_data)
        fw_data = fw_path.read_bytes()

        await self._send_intel_vendor_cmd(self._INTEL_ENTER_MFG)

        bp = self._BOOT_PARAMS_LEGACY_RSA
        if len(fw_data) < bp.write_offset:
            raise RuntimeError(
                f"Intel: firmware too small ({len(fw_data)} bytes, "
                f"need at least {bp.write_offset})"
            )

        boot_address = await self._secure_send_firmware(fw_data, bp)
        logger.info("Intel legacy: firmware download complete, boot_address=0x%08X", boot_address)

        logger.info("Intel legacy: waiting for firmware load complete event...")
        try:
            await self._wait_for_vendor_event(expected_type=0x06, timeout=10.0)
            logger.info("Intel legacy: firmware load complete")
        except TimeoutError:
            logger.info("Intel legacy: no firmware load complete event; continuing")

        await self._intel_reset_newgen(boot_address)
        logger.info("Intel legacy: waiting for boot complete event...")
        try:
            await self._wait_for_vendor_event(expected_type=0x02, timeout=10.0)
            logger.info("Intel legacy: boot complete")
        except TimeoutError:
            logger.info("Intel legacy: no boot complete event; verifying with Read Version")

        # Verify
        version_data = await self._send_intel_vendor_cmd(self._INTEL_READ_VERSION)
        fw_variant = self._parse_fw_variant(version_data)
        if not self._is_operational(hw_variant, fw_variant):
            raise RuntimeError(
                f"Intel firmware load failed: fw_variant=0x{fw_variant:02X}, "
                f"expected operational variant for hw_variant=0x{hw_variant:02X}"
            )

    # ── Shared helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_intel_vendor_command(ocf: int, params: bytes = b"") -> bytes:
        opcode = (0x3F << 10) | ocf
        return opcode.to_bytes(2, "little") + len(params).to_bytes(1, "little") + params

    async def _send_intel_vendor_cmd(
        self,
        ocf: int,
        params: bytes = b"",
        *,
        context: str | None = None,
        timeout: float = 5.0,
    ) -> bytes:
        """Send Intel vendor command (OGF=0x3F) and await Command Complete Event."""
        opcode = (0x3F << 10) | ocf
        command = self._build_intel_vendor_command(ocf, params)
        label = f"vendor cmd 0x{opcode:04X}"
        if context:
            label = f"{label} ({context})"
        is_payload_fragment = bool(context and context.startswith("payload offset="))
        wait_logger = logger.debug if is_payload_fragment else logger.info
        wait_logger("Intel: %s waiting for Command Complete timeout=%gs", label, timeout)
        await self._control_out(command)
        try:
            event = await self._wait_for_event(timeout=timeout)
        except TimeoutError:
            logger.info("Intel: %s timeout after %gs", label, timeout)
            raise
        except asyncio.CancelledError:
            logger.info("Intel: %s cancelled while waiting for Command Complete", label)
            raise
        logger.debug("Intel: %s complete", label)
        return event

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

    def _parse_hw_revision(self, event_data: bytes) -> int:
        """Extract hw_revision from legacy HCI_Intel_Read_Version response at [8]."""
        if len(event_data) >= 9:
            return event_data[8]
        return 0xFF

    def _parse_fw_revision(self, event_data: bytes) -> int:
        """Extract fw_revision from legacy HCI_Intel_Read_Version response at [10]."""
        if len(event_data) >= 11:
            return event_data[10]
        return 0xFF

    def _is_operational(self, hw_variant: int, fw_variant: int) -> bool:
        """Return True if device is operational (legacy protocol)."""
        if hw_variant >= self._HW_VARIANT_NEW_PLATFORM_MIN:
            return fw_variant == self._FW_VARIANT_OPERATIONAL_NEW
        return fw_variant in {
            self._FW_VARIANT_OPERATIONAL,
            self._FW_VARIANT_OPERATIONAL_LEGACY_FW,
        }

    def _find_firmware(self, version_data: bytes | None = None) -> Path:
        """Locate Intel firmware file using FirmwareManager (legacy: glob pattern)."""
        mgr = FirmwareManager(
            vendor="intel",
            extra_dirs=self._extra_fw_dirs,
            policy=self._firmware_policy,
        )
        if version_data is not None:
            exact_name = self._legacy_firmware_name(version_data)
            if exact_name is not None:
                return mgr.find(exact_name)
        pattern = self._chip_info.firmware_pattern if self._chip_info else "ibt-*"
        for search_dir in mgr._search_dirs():
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return matches[0]
        return mgr.find(pattern)

    def _legacy_firmware_name(self, version_data: bytes) -> str | None:
        hw_variant = self._parse_hw_variant(version_data)
        hw_revision = self._parse_hw_revision(version_data)
        fw_revision = self._parse_fw_revision(version_data)
        if hw_variant in {0x11, 0x12, 0x13, 0x14}:
            return f"ibt-{hw_variant}-{hw_revision}-{fw_revision}.sfi"
        return None

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
