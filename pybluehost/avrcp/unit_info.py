"""AVRCP UNIT_INFO + SUBUNIT_INFO command/response builders (AV/C v4.0 §11.2)."""
from __future__ import annotations

import struct

from pybluehost.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
)
from pybluehost.avrcp.frame import AVCFrame


def build_unit_info_command() -> AVCFrame:
    """STATUS command, UNIT subunit (type=0x1F, id=7), operands = 5 × 0xFF."""
    return AVCFrame(
        ctype=AVCCtype.STATUS,
        subunit_type=AVCSubunitType.UNIT,
        subunit_id=7,
        opcode=AVCOpCode.UNIT_INFO,
        operands=bytes([0xFF] * 5),
    )


def build_unit_info_response(*, company_id: int) -> AVCFrame:
    """STABLE response with company_id in operand bytes 2..4 (big-endian)."""
    company_be = struct.pack(">I", company_id & 0xFFFFFF)[1:]    # 3 bytes
    operands = bytes([
        0x07,        # reserved
        0xFF,        # unit_type=UNIT(0x1F) << 3 | unit_id=7
    ]) + company_be
    return AVCFrame(
        ctype=AVCCtype.STABLE,
        subunit_type=AVCSubunitType.UNIT,
        subunit_id=7,
        opcode=AVCOpCode.UNIT_INFO,
        operands=operands,
    )


def parse_unit_info_response(frame: AVCFrame) -> int:
    """Returns the company_id from a UNIT_INFO STABLE response."""
    if frame.opcode != AVCOpCode.UNIT_INFO:
        raise ValueError("not a UNIT_INFO frame")
    if len(frame.operands) < 5:
        raise ValueError("UNIT_INFO response too short")
    return struct.unpack(">I", b"\x00" + bytes(frame.operands[2:5]))[0]


def build_subunit_info_command(*, page: int = 0) -> AVCFrame:
    """STATUS command with page/extension byte + 4 × 0xFF."""
    if not 0 <= page <= 7:
        raise ValueError(f"page {page} out of range 0..7")
    return AVCFrame(
        ctype=AVCCtype.STATUS,
        subunit_type=AVCSubunitType.UNIT,
        subunit_id=7,
        opcode=AVCOpCode.SUBUNIT_INFO,
        operands=bytes([(page & 0x7) << 4 | 0x07]) + bytes([0xFF] * 4),
    )


def build_subunit_info_response(
    *, subunits: list[tuple[AVCSubunitType, int]] | None = None,
) -> AVCFrame:
    """STABLE response advertising subunits the local target supports.

    Default: a single PANEL subunit (the AVRCP target case)."""
    if subunits is None:
        subunits = [(AVCSubunitType.PANEL, 0)]
    encoded = bytearray()
    for sub_type, sub_id in subunits[:4]:
        encoded.append((int(sub_type) & 0x1F) << 3 | (sub_id & 0x7))
    while len(encoded) < 4:
        encoded.append(0xFF)
    return AVCFrame(
        ctype=AVCCtype.STABLE,
        subunit_type=AVCSubunitType.UNIT,
        subunit_id=7,
        opcode=AVCOpCode.SUBUNIT_INFO,
        operands=bytes([0x07]) + bytes(encoded),
    )


def parse_subunit_info_response(frame: AVCFrame) -> list[tuple[AVCSubunitType, int]]:
    """Returns the list of (subunit_type, subunit_id) advertised by the responder."""
    if frame.opcode != AVCOpCode.SUBUNIT_INFO:
        raise ValueError("not a SUBUNIT_INFO frame")
    if len(frame.operands) < 5:
        raise ValueError("SUBUNIT_INFO response too short")
    out: list[tuple[AVCSubunitType, int]] = []
    for b in frame.operands[1:5]:
        if b == 0xFF:
            continue
        sub_type = AVCSubunitType((b >> 3) & 0x1F)
        sub_id = b & 0x7
        out.append((sub_type, sub_id))
    return out
