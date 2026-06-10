"""AVDTP v1.3 signaling: message encode/decode + transaction layer.

This module defines the wire format. Higher-level signaling commands
(DISCOVER/GET_CAPS/etc.) and the L2CAP-channel-aware transaction tracker
live in `session.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.avdtp.constants import (
    AVDTPMessageType, AVDTPPacketType, AVDTPSignalID,
    MediaType, ServiceCategory, TSEP,
)


@dataclass
class AVDTPMessage:
    """One AVDTP signaling packet (AVDTP v1.3 §8.4).

    Single-packet form only (no fragmentation); fragmentation is handled at the
    transaction layer in `session.py` if the payload exceeds the L2CAP MTU.
    """
    transaction_id: int
    packet_type: AVDTPPacketType
    message_type: AVDTPMessageType
    signal_id: AVDTPSignalID
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


# ---------------------------------------------------------------------------
# AVDTP payload codecs — DISCOVER + GET_CAPABILITIES
# ---------------------------------------------------------------------------


def encode_sep_descriptor(
    seid: int, *, in_use: bool, media_type: MediaType, tsep: TSEP
) -> bytes:
    """Encode one 2-byte SEP descriptor (AVDTP v1.3 §8.6.2)."""
    if not 1 <= seid <= 62:
        raise ValueError(f"seid {seid} out of range 1..62")
    b0 = (seid & 0x3F) << 2 | (1 if in_use else 0) << 1
    b1 = (int(media_type) & 0xF) << 4 | (int(tsep) & 0x1) << 3
    return bytes([b0, b1])


def decode_sep_descriptors(data: bytes) -> list[tuple[int, bool, MediaType, TSEP]]:
    """Decode the DISCOVER response payload — N × 2-byte SEP descriptors."""
    if len(data) % 2 != 0:
        raise ValueError(f"SEP descriptor list truncated (length {len(data)}, want multiple of 2)")
    out: list[tuple[int, bool, MediaType, TSEP]] = []
    for i in range(0, len(data), 2):
        b0, b1 = data[i], data[i + 1]
        seid = (b0 >> 2) & 0x3F
        in_use = bool((b0 >> 1) & 0x1)
        media_type = MediaType((b1 >> 4) & 0xF)
        tsep = TSEP((b1 >> 3) & 0x1)
        out.append((seid, in_use, media_type, tsep))
    return out


def encode_capabilities(caps: list[tuple[ServiceCategory, bytes]]) -> bytes:
    """Encode the GET_CAPABILITIES response payload — sequence of service-cap TLVs."""
    out = bytearray()
    for category, payload in caps:
        if len(payload) > 0xFF:
            raise ValueError(f"capability payload too long ({len(payload)} > 255)")
        out.append(int(category))
        out.append(len(payload))
        out += payload
    return bytes(out)


def decode_capabilities(data: bytes) -> list[tuple[ServiceCategory, bytes]]:
    out: list[tuple[ServiceCategory, bytes]] = []
    i = 0
    while i < len(data):
        if i + 2 > len(data):
            raise ValueError("capability TLV truncated at end of buffer")
        category = ServiceCategory(data[i])
        losc = data[i + 1]
        if i + 2 + losc > len(data):
            raise ValueError(
                f"capability LOSC overruns buffer for {category.name} "
                f"(i={i}, losc={losc}, buffer_len={len(data)})"
            )
        out.append((category, bytes(data[i + 2:i + 2 + losc])))
        i += 2 + losc
    return out


def encode_seid_byte(seid: int) -> int:
    """Encode a 1-byte ACP SEID: SEID(6) << 2 | RFA(2)."""
    if not 1 <= seid <= 62:
        raise ValueError(f"seid {seid} out of range 1..62")
    return (seid & 0x3F) << 2


def decode_seid_byte(b: int) -> int:
    return (b >> 2) & 0x3F
