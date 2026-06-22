"""BTP frame encode/decode (design spec §11.2)."""
from __future__ import annotations

import struct
from dataclasses import dataclass


BTP_HEADER_SIZE = 5
_MAX_DATA_LENGTH = 0xFFFF


@dataclass(frozen=True)
class BtpFrame:
    service: int               # u8 — Service ID
    opcode: int                # u8 — opcode within the service
    controller_index: int      # u8 — usually 0 (first controller) or 0xFF (none)
    data: bytes                # variable, ≤ 65535 bytes


def encode_btp_frame(frame: BtpFrame) -> bytes:
    if len(frame.data) > _MAX_DATA_LENGTH:
        raise ValueError(
            f"BTP frame data length {len(frame.data)} exceeds u16 max "
            f"({_MAX_DATA_LENGTH})"
        )
    return struct.pack(
        "<BBBH",
        frame.service & 0xFF,
        frame.opcode & 0xFF,
        frame.controller_index & 0xFF,
        len(frame.data),
    ) + frame.data


def decode_btp_frame(raw: bytes) -> BtpFrame:
    if len(raw) < BTP_HEADER_SIZE:
        raise ValueError(
            f"BTP frame header truncated: got {len(raw)} bytes, need >= {BTP_HEADER_SIZE}"
        )
    service, opcode, ctrl_idx, length = struct.unpack("<BBBH", raw[:BTP_HEADER_SIZE])
    if len(raw) < BTP_HEADER_SIZE + length:
        raise ValueError(
            f"BTP frame data truncated: header says {length} bytes, "
            f"got {len(raw) - BTP_HEADER_SIZE}"
        )
    return BtpFrame(
        service=service,
        opcode=opcode,
        controller_index=ctrl_idx,
        data=raw[BTP_HEADER_SIZE : BTP_HEADER_SIZE + length],
    )
