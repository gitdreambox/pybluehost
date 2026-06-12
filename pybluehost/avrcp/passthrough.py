"""AVRCP v1.6 §4.6 — PASS_THROUGH command + response encode/decode."""
from __future__ import annotations

from dataclasses import dataclass, field

from pybluehost.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType, AVRCPOperationID,
)
from pybluehost.avrcp.frame import AVCFrame


_STATE_RELEASED_BIT = 0x80   # AV/C spec: 1 = Released, 0 = Pressed


@dataclass
class PassThroughCommand:
    """AVRCP v1.6 §4.6 PASS_THROUGH command.

    The state bit (high bit of operand byte 0) is 0 for Pressed, 1 for Released.
    Most one-shot commands (PLAY/PAUSE/STOP) send Pressed immediately followed
    by Released (~100 ms apart) — the controller class can issue both as a pair.
    """
    operation_id: int           # AVRCPOperationID, 7 bits
    pressed: bool = True
    operation_data: bytes = field(default=b"")

    def to_avcframe(self, *, ctype: AVCCtype = AVCCtype.CONTROL) -> AVCFrame:
        op_byte = (0 if self.pressed else _STATE_RELEASED_BIT) | (self.operation_id & 0x7F)
        operands = bytes([op_byte, len(self.operation_data)]) + self.operation_data
        return AVCFrame(
            ctype=ctype,
            subunit_type=AVCSubunitType.PANEL,
            subunit_id=0,
            opcode=AVCOpCode.PASS_THROUGH,
            operands=operands,
        )

    @classmethod
    def from_avcframe(cls, frame: AVCFrame) -> "PassThroughCommand":
        if frame.opcode != AVCOpCode.PASS_THROUGH:
            raise ValueError(
                f"not a PASS_THROUGH frame (opcode 0x{int(frame.opcode):02X})"
            )
        if len(frame.operands) < 2:
            raise ValueError("PASS_THROUGH operands too short")
        op_byte = frame.operands[0]
        data_len = frame.operands[1]
        if len(frame.operands) < 2 + data_len:
            raise ValueError("PASS_THROUGH operation_data truncated")
        return cls(
            operation_id=op_byte & 0x7F,
            pressed=(op_byte & _STATE_RELEASED_BIT) == 0,
            operation_data=bytes(frame.operands[2:2 + data_len]),
        )


@dataclass
class PassThroughResponse:
    """Response to a PASS_THROUGH command. Wraps an AV/C frame with one of:
    ACCEPTED / NOT_IMPLEMENTED / REJECTED."""
    ctype: AVCCtype
    operation_id: int
    pressed: bool
    operation_data: bytes = field(default=b"")

    def to_avcframe(self) -> AVCFrame:
        op_byte = (0 if self.pressed else _STATE_RELEASED_BIT) | (self.operation_id & 0x7F)
        operands = bytes([op_byte, len(self.operation_data)]) + self.operation_data
        return AVCFrame(
            ctype=self.ctype,
            subunit_type=AVCSubunitType.PANEL,
            subunit_id=0,
            opcode=AVCOpCode.PASS_THROUGH,
            operands=operands,
        )

    @classmethod
    def accepted(cls, *, operation_id: int, pressed: bool) -> "PassThroughResponse":
        return cls(ctype=AVCCtype.ACCEPTED, operation_id=operation_id, pressed=pressed)

    @classmethod
    def not_implemented(cls, *, operation_id: int, pressed: bool) -> "PassThroughResponse":
        return cls(
            ctype=AVCCtype.NOT_IMPLEMENTED, operation_id=operation_id, pressed=pressed,
        )

    @classmethod
    def rejected(cls, *, operation_id: int, pressed: bool) -> "PassThroughResponse":
        return cls(ctype=AVCCtype.REJECTED, operation_id=operation_id, pressed=pressed)
