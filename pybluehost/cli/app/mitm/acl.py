"""HCI ACL transparent-relay core: L2CAP PDU reassembly, CID routing, cross-buffer refragmentation.

This module only understands HCI fragment boundaries + the L2CAP basic header (2-byte
length + 2-byte CID), is BLE/BR-agnostic, and is therefore shared by both transports.
"""
from __future__ import annotations

import struct
from enum import Enum, auto

from pybluehost.hci.packets import HCIACLData

# HCI ACL Packet Boundary flags (Core Vol4 Part E §5.4.2)
PB_FIRST_NON_FLUSH = 0x00  # host→controller first fragment (non-auto-flush)
PB_CONTINUATION = 0x01     # continuation fragment
PB_FIRST_FLUSH = 0x02      # first fragment (auto-flush; common on the receive path)

# Fixed CIDs
CID_BR_SIGNALING = 0x0001
CID_ATT = 0x0004
CID_LE_SIGNALING = 0x0005
CID_SMP = 0x0006


class RelayDirection(Enum):
    PHONE_TO_TARGET = "phone→target"
    TARGET_TO_PHONE = "target→phone"


class CidAction(Enum):
    RELAY = auto()          # forward transparently (ATT/dynamic/signaling)
    TERMINATE_SMP = auto()  # terminate locally (BLE SMP, taken over by MITM-2)


def classify(cid: int) -> CidAction:
    """Decide whether an L2CAP CID is terminated locally or forwarded transparently."""
    if cid == CID_SMP:
        return CidAction.TERMINATE_SMP
    return CidAction.RELAY


def encode_l2cap_basic(cid: int, payload: bytes) -> bytes:
    """Encode (cid, payload) into an L2CAP basic-header frame."""
    return struct.pack("<HH", len(payload), cid) + payload


class L2capReassembler:
    """Reassemble a single direction of HCI ACL fragments → complete L2CAP PDUs.

    Usage: one instance per connection direction; accumulates by PB flag and peels out all
    complete PDUs. A continuation fragment (PB_CONTINUATION) appends to the buffer; a
    non-continuation is treated as the start of a new message (overwrites the buffer).
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, acl: HCIACLData) -> list[tuple[int, bytes]]:
        if acl.pb_flag == PB_CONTINUATION:
            self._buf += acl.data
        else:
            self._buf = acl.data

        out: list[tuple[int, bytes]] = []
        while len(self._buf) >= 4:
            length = struct.unpack_from("<H", self._buf, 0)[0]
            total = 4 + length
            if len(self._buf) < total:
                break
            cid = struct.unpack_from("<H", self._buf, 2)[0]
            out.append((cid, self._buf[4:total]))
            self._buf = self._buf[total:]
        return out


def fragment(
    *, handle: int, l2cap_pdu: bytes, max_payload: int,
    first_pb: int = PB_FIRST_NON_FLUSH,
) -> list[HCIACLData]:
    """Split a complete L2CAP PDU into HCI ACL fragments of at most max_payload.

    The first fragment uses first_pb, the rest PB_CONTINUATION. max_payload comes from the
    peer controller's acl_packet_length / le_acl_packet_length.
    """
    if max_payload <= 0:
        raise ValueError("max_payload 必须 > 0")
    frags = [
        HCIACLData(handle=handle, pb_flag=first_pb, data=l2cap_pdu[:max_payload])
    ]
    rest = l2cap_pdu[max_payload:]
    while rest:
        frags.append(
            HCIACLData(handle=handle, pb_flag=PB_CONTINUATION, data=rest[:max_payload])
        )
        rest = rest[max_payload:]
    return frags
