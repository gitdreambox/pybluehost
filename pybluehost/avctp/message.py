"""AVCTP v1.4 message encode/decode.

Single-packet form (PT=SINGLE) only in this module's constructor — START/
CONTINUE/END fragmentation is handled at the session layer in Task 3."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from pybluehost.avctp.constants import (
    AVCTPMessageDirection, AVCTPPacketType,
)


@dataclass
class AVCTPMessage:
    """One AVCTP packet (AVCTP v1.4 §6.1).

    `num_packets` is the START-packet only count of total fragments; it's
    written between byte 0 and the profile_id when packet_type == START.
    Other packet types ignore it.
    """
    transaction_label: int
    packet_type: AVCTPPacketType
    cr: AVCTPMessageDirection
    ipid: int
    profile_id: int
    payload: bytes = b""
    num_packets: int = 0

    def to_bytes(self) -> bytes:
        if not 0 <= self.transaction_label <= 0xF:
            raise ValueError(
                f"transaction_label {self.transaction_label} out of range 0..15"
            )
        b0 = (
            (self.transaction_label & 0xF) << 4
            | (int(self.packet_type) & 0x3) << 2
            | (int(self.cr) & 0x1) << 1
            | (self.ipid & 0x1)
        )
        if self.packet_type == AVCTPPacketType.START:
            return (
                bytes([b0, self.num_packets & 0xFF])
                + struct.pack(">H", self.profile_id & 0xFFFF)
                + self.payload
            )
        if self.packet_type in (AVCTPPacketType.CONTINUE, AVCTPPacketType.END):
            # CONTINUE/END carry only TID/PT/CR — no profile_id, just payload.
            return bytes([b0]) + self.payload
        # SINGLE
        return bytes([b0]) + struct.pack(">H", self.profile_id & 0xFFFF) + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "AVCTPMessage":
        if len(data) < 1:
            raise ValueError("AVCTP message too short: empty buffer")
        b0 = data[0]
        tid = (b0 >> 4) & 0xF
        pt = AVCTPPacketType((b0 >> 2) & 0x3)
        cr = AVCTPMessageDirection((b0 >> 1) & 0x1)
        ipid = b0 & 0x1

        if pt == AVCTPPacketType.START:
            if len(data) < 4:
                raise ValueError(f"AVCTP START packet too short: {len(data)} bytes (need >= 4)")
            num_packets = data[1]
            profile_id = struct.unpack(">H", data[2:4])[0]
            payload = bytes(data[4:])
            return cls(
                transaction_label=tid, packet_type=pt, cr=cr, ipid=ipid,
                profile_id=profile_id, payload=payload, num_packets=num_packets,
            )

        if pt in (AVCTPPacketType.CONTINUE, AVCTPPacketType.END):
            # No profile_id in continuation packets.
            return cls(
                transaction_label=tid, packet_type=pt, cr=cr, ipid=ipid,
                profile_id=0, payload=bytes(data[1:]),
            )

        # SINGLE
        if len(data) < 3:
            raise ValueError(f"AVCTP SINGLE too short: {len(data)} bytes (need >= 3)")
        profile_id = struct.unpack(">H", data[1:3])[0]
        return cls(
            transaction_label=tid, packet_type=pt, cr=cr, ipid=ipid,
            profile_id=profile_id, payload=bytes(data[3:]),
        )
