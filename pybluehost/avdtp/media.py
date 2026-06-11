"""AVDTP Media packet (AVDTP v1.3 §4.3.2 / RTP RFC 3550 §5.1).

Header is RTP-style; payload begins with 1-byte SBC frame count then
concatenated SBC frames (A2DP v1.4 §4.3.4)."""
from __future__ import annotations

import struct
from dataclasses import dataclass


_PAYLOAD_TYPE_DYNAMIC = 0x60   # PT=96, A2DP convention
_RTP_VERSION = 2


@dataclass
class AVDTPMediaPacket:
    """One media packet over the AVDTP transport channel.

    For A2DP/SBC: V=2, P=0, X=0, CC=0, M=0, PT=96. Header is 12 bytes,
    followed by 1-byte SBC frame count and 1..N SBC frames.
    """
    sequence_number: int
    timestamp: int
    ssrc: int
    payload: bytes = b""
    frame_count: int = 0

    def to_bytes(self) -> bytes:
        b0 = (_RTP_VERSION & 0x3) << 6   # V=2, P=0, X=0, CC=0
        b1 = _PAYLOAD_TYPE_DYNAMIC       # M=0, PT=96
        header = struct.pack(
            ">BBHII",
            b0, b1,
            self.sequence_number & 0xFFFF,
            self.timestamp & 0xFFFFFFFF,
            self.ssrc & 0xFFFFFFFF,
        )
        # SBC frame count (A2DP §4.3.4): 8-bit field, low 4 bits = count
        frame_count_byte = bytes([self.frame_count & 0x0F])
        return header + frame_count_byte + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "AVDTPMediaPacket":
        if len(data) < 13:    # 12-byte RTP header + 1-byte frame count
            raise ValueError(f"AVDTP media packet too short: {len(data)} bytes (need ≥ 13)")
        b0 = data[0]
        version = (b0 >> 6) & 0x3
        if version != _RTP_VERSION:
            raise ValueError(f"unsupported RTP version {version} (expected 2)")
        seq, ts, ssrc = struct.unpack(">HII", data[2:12])
        frame_count = data[12] & 0x0F
        return cls(
            sequence_number=seq,
            timestamp=ts,
            ssrc=ssrc,
            payload=bytes(data[13:]),
            frame_count=frame_count,
        )
