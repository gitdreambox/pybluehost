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


import struct
from datetime import datetime, timezone


# Ellisys Service IDs / object tags (recovered from the working demo +
# bex400a_injection_api samples)
_ELLISYS_HCI_INJECTION_SERVICE_ID = 0x0002
_ELLISYS_HCI_INJECTION_SERVICE_VERSION = 0x01
_OBJ_DATETIME_NS = 0x02
_OBJ_BITRATE = 0x80
_OBJ_PACKET_TYPE = 0x81
_OBJ_PACKET_DATA = 0x82
_OBJ_CONTROLLER_INDEX = 0x83

# USB full-speed nominal bit rate (informational field in the injection packet)
ELLISYS_HCI_USB_FULL_SPEED_BITRATE = 12_000_000.0


def _utc_datetime_ns_fields(wall_clock: datetime) -> tuple[int, int, int, int, int]:
    """Return (year, month, day, ns_low, ns_high) where ns is nanoseconds
    since UTC midnight of that day, split into low u32 / high u16."""
    if wall_clock.tzinfo is not None:
        wall_clock = wall_clock.astimezone(timezone.utc)
    ns = (
        ((wall_clock.hour * 60 + wall_clock.minute) * 60 + wall_clock.second)
        * 1_000_000_000
        + wall_clock.microsecond * 1_000
    )
    return (
        wall_clock.year,
        wall_clock.month,
        wall_clock.day,
        ns & 0xFFFFFFFF,
        (ns >> 32) & 0xFFFF,
    )


def encode_ellisys_injection_packet(
    wall_clock: datetime,
    bit_rate: float,
    packet_type: int,
    hci_payload: bytes,
    controller_index: int = 0,
) -> bytes:
    """Encode an Ellisys HCI injection UDP packet (design spec §3.2 / §5.5).

    `packet_type` is an Ellisys InjectedHciPacketType byte (use
    `ellisys_packet_type(h4, direction)` to compute). `hci_payload` must NOT
    include the H4 type byte. Byte layout mirrors the working demo's
    `prepare_ellisys_hci_injection_packet`.
    """
    year, month, day, ns_low, ns_high = _utc_datetime_ns_fields(wall_clock)
    return b"".join([
        struct.pack(
            "<HB",
            _ELLISYS_HCI_INJECTION_SERVICE_ID,
            _ELLISYS_HCI_INJECTION_SERVICE_VERSION,
        ),
        struct.pack("<BHBBIH", _OBJ_DATETIME_NS, year, month, day, ns_low, ns_high),
        struct.pack("<BB", _OBJ_CONTROLLER_INDEX, controller_index),
        struct.pack("<Bf", _OBJ_BITRATE, bit_rate),
        struct.pack("<BB", _OBJ_PACKET_TYPE, packet_type),
        struct.pack("<B", _OBJ_PACKET_DATA),
        hci_payload,
    ])
