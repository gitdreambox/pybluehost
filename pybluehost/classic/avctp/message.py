"""AVCTP v1.4 §6.1 message encode/decode — SINGLE/START/CONTINUE/END packet forms.

This module handles per-packet wire format. Reassembling fragmented messages
(stashing START + CONTINUEs and emitting a unified payload on END) is the
session-layer concern; see `pybluehost.classic.avctp.session` (Task 3+)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from pybluehost.classic.avctp.constants import (
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
            if not 1 <= self.num_packets <= 0xFF:
                raise ValueError(
                    f"num_packets {self.num_packets} out of range 1..255 (AVCTP v1.4 §6.3)"
                )
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


class AVCTPReassembler:
    """AVCTP v1.4 §6.3 fragmentation reassembler.

    One instance per peer L2CAP channel. Stash START/CONTINUE bytes per
    transaction_label; return the reassembled `AVCTPMessage` (logically a
    SINGLE-form message) on END. SINGLE packets pass through immediately.
    Orphan CONTINUE/END fragments (no matching prior START) are dropped silently
    per the spec.
    """

    def __init__(self) -> None:
        self._partial: dict[int, AVCTPMessage] = {}

    def feed(self, msg: AVCTPMessage) -> Optional[AVCTPMessage]:
        if msg.packet_type == AVCTPPacketType.SINGLE:
            return msg

        if msg.packet_type == AVCTPPacketType.START:
            # Stash a working copy whose final form is logically SINGLE.
            self._partial[msg.transaction_label] = AVCTPMessage(
                transaction_label=msg.transaction_label,
                packet_type=AVCTPPacketType.SINGLE,
                cr=msg.cr, ipid=msg.ipid,
                profile_id=msg.profile_id,
                payload=bytes(msg.payload),
            )
            return None

        # CONTINUE or END
        partial = self._partial.get(msg.transaction_label)
        if partial is None:
            # Orphan fragment — drop silently.
            return None
        partial.payload = partial.payload + bytes(msg.payload)

        if msg.packet_type == AVCTPPacketType.END:
            self._partial.pop(msg.transaction_label, None)
            return partial

        return None
