"""AVDTP v1.3 signaling: message encode/decode + transaction layer.

This module defines the wire format. Higher-level signaling commands
(DISCOVER/GET_CAPS/etc.) and the L2CAP-channel-aware transaction tracker
live in `session.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.avdtp.constants import (
    AVDTPMessageType, AVDTPPacketType, AVDTPSignalID,
)


@dataclass
class AVDTPMessage:
    """One AVDTP signaling packet (AVDTP v1.3 §8.4).

    Single-packet form only (no fragmentation); fragmentation is handled at the
    transaction layer in `session.py` if the payload exceeds the L2CAP MTU.
    """
    transaction_id: int
    packet_type: int
    message_type: int
    signal_id: int
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        if not 0 <= self.transaction_id <= 0xF:
            raise ValueError(f"transaction_id {self.transaction_id} out of range 0..15")
        b0 = (
            (self.transaction_id & 0xF) << 4
            | (int(self.packet_type) & 0x3) << 2
            | (int(self.message_type) & 0x3)
        )
        b1 = int(self.signal_id) & 0x3F
        return bytes([b0, b1]) + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "AVDTPMessage":
        if len(data) < 2:
            raise ValueError(f"AVDTP message too short: {len(data)} bytes (need ≥ 2)")
        b0 = data[0]
        b1 = data[1]
        return cls(
            transaction_id=(b0 >> 4) & 0xF,
            packet_type=AVDTPPacketType((b0 >> 2) & 0x3),
            message_type=AVDTPMessageType(b0 & 0x3),
            signal_id=AVDTPSignalID(b1 & 0x3F),
            payload=bytes(data[2:]),
        )
