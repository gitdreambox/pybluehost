"""Realtek Bluetooth vendor-specific HCI constants and response parsers.

These opcodes are used by RealtekUSBTransport during firmware loading.
All opcodes use OGF=0x3F (VENDOR) per Bluetooth Core Spec Vol 4, Part E §7.6.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pybluehost.hci.constants import OGF, make_opcode

# ---------------------------------------------------------------------------
# Vendor opcodes
# ---------------------------------------------------------------------------
HCI_VS_REALTEK_READ_ROM_VERSION: int = make_opcode(OGF.VENDOR, 0x6D)  # 0xFC6D
HCI_VS_REALTEK_WRITE_FIRMWARE: int = make_opcode(OGF.VENDOR, 0x20)  # 0xFC20


@dataclass
class RealtekROMVersion:
    """Parsed return parameters of HCI_VS_Realtek_Read_ROM_Version (0xFC6D).

    The 3-byte return parameter layout matches the Linux kernel
    drivers/bluetooth/btrtl.h rtl_rom_version_evt struct.
    """

    status: int
    rom_version: int  # uint16 LE

    _FORMAT = "<BH"
    _SIZE = struct.calcsize(_FORMAT)  # 3

    @classmethod
    def from_bytes(cls, data: bytes) -> RealtekROMVersion:
        if len(data) < cls._SIZE:
            raise ValueError(
                f"RealtekROMVersion requires {cls._SIZE} bytes, got {len(data)}"
            )
        status, rom_version = struct.unpack_from(cls._FORMAT, data)
        return cls(status=status, rom_version=rom_version)

    def to_bytes(self) -> bytes:
        return struct.pack(self._FORMAT, self.status, self.rom_version)
