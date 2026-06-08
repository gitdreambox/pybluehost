"""Ellisys Bluetooth Analyzer injection — pure encoding + Windows backend."""
from __future__ import annotations

from pybluehost.core.trace import Direction


# H4 packet types (mirror pybluehost.hci.packets.HCI_*_PACKET constants)
_H4_COMMAND = 0x01
_H4_ACL = 0x02
_H4_SCO = 0x03
_H4_EVENT = 0x04
_H4_ISO = 0x05


def ellisys_packet_type(h4_type: int, direction: Direction) -> int:
    """Map (H4 packet type, direction) → Ellisys InjectedHciPacketType byte.

    See design spec §3.2. ACL/SCO/ISO have FromHost/FromController variants.
    """
    if h4_type == _H4_COMMAND:
        return 0x01
    if h4_type == _H4_EVENT:
        return 0x84
    if h4_type == _H4_ACL:
        return 0x02 if direction == Direction.DOWN else 0x82
    if h4_type == _H4_SCO:
        return 0x03 if direction == Direction.DOWN else 0x83
    if h4_type == _H4_ISO:
        return 0x05 if direction == Direction.DOWN else 0x85
    raise ValueError(f"unknown H4 packet type: 0x{h4_type:02X}")
