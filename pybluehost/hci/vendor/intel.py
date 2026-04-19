"""Intel Bluetooth vendor-specific HCI constants and response parsers.

These opcodes are used by IntelUSBTransport during firmware loading.
All opcodes use OGF=0x3F (VENDOR) per Bluetooth Core Spec Vol 4, Part E §7.6.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pybluehost.hci.constants import OGF, make_opcode

# ---------------------------------------------------------------------------
# Vendor opcodes
# ---------------------------------------------------------------------------
HCI_VS_INTEL_READ_VERSION: int = make_opcode(OGF.VENDOR, 0x05)  # 0xFC05
HCI_VS_INTEL_WRITE_FIRMWARE: int = make_opcode(OGF.VENDOR, 0x20)  # 0xFC20

# ---------------------------------------------------------------------------
# TLV type constants (Intel secure boot firmware packets)
# ---------------------------------------------------------------------------
INTEL_TLV_TYPE_CNV: int = 0x10  # Connectivity Version (CNVi/CNVr)
INTEL_TLV_TYPE_TIMESTAMP: int = 0x18  # Firmware build timestamp


@dataclass
class IntelReadVersionResponse:
    """Parsed return parameters of HCI_VS_Intel_Read_Version (0xFC05).

    The 10-byte return parameter layout matches the Linux kernel
    drivers/bluetooth/btintel.h IntelVersion struct.
    """

    status: int
    hw_platform: int
    hw_variant: int
    hw_revision: int
    fw_variant: int
    fw_revision: int
    fw_build_num: int
    fw_build_week: int
    fw_build_year: int
    fw_patch_num: int

    _FORMAT = "<BBBBBBBBBB"
    _SIZE = struct.calcsize(_FORMAT)  # 10

    @classmethod
    def from_bytes(cls, data: bytes) -> IntelReadVersionResponse:
        if len(data) < cls._SIZE:
            raise ValueError(
                f"IntelReadVersionResponse requires {cls._SIZE} bytes, got {len(data)}"
            )
        fields = struct.unpack_from(cls._FORMAT, data)
        return cls(*fields)

    def to_bytes(self) -> bytes:
        return struct.pack(
            self._FORMAT,
            self.status, self.hw_platform, self.hw_variant, self.hw_revision,
            self.fw_variant, self.fw_revision, self.fw_build_num,
            self.fw_build_week, self.fw_build_year, self.fw_patch_num,
        )
