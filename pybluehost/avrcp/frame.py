"""AV/C frame encode/decode for AVRCP."""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.avrcp.constants import AVCCtype, AVCOpCode, AVCSubunitType


@dataclass
class AVCFrame:
    """AV/C v4.0 §6 frame: Ctype, Subunit type/id, OpCode, operands.

    The high nibble of byte 0 is reserved (zero); the low nibble is Ctype.
    Byte 1: subunit_type(5) << 3 | subunit_id(3).
    Byte 2: OpCode.
    """
    ctype: AVCCtype
    subunit_type: AVCSubunitType
    subunit_id: int
    opcode: AVCOpCode
    operands: bytes = b""

    def to_bytes(self) -> bytes:
        if not 0 <= self.subunit_id <= 7:
            raise ValueError(f"subunit_id {self.subunit_id} out of range 0..7")
        b0 = int(self.ctype) & 0xF
        b1 = (int(self.subunit_type) & 0x1F) << 3 | (self.subunit_id & 0x7)
        b2 = int(self.opcode) & 0xFF
        return bytes([b0, b1, b2]) + self.operands

    @classmethod
    def from_bytes(cls, data: bytes) -> "AVCFrame":
        if len(data) < 3:
            raise ValueError(f"AV/C frame too short: {len(data)} bytes (need >= 3)")
        return cls(
            ctype=AVCCtype(data[0] & 0xF),
            subunit_type=AVCSubunitType((data[1] >> 3) & 0x1F),
            subunit_id=data[1] & 0x7,
            opcode=AVCOpCode(data[2]),
            operands=bytes(data[3:]),
        )
