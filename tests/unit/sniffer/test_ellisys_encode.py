"""Byte-layout tests for the Ellisys HCI injection packet encoder.

The second test is a self-contained golden cross-check: it independently
reconstructs the canonical Ellisys injection byte layout (the layout the
working demo `prepare_ellisys_hci_injection_packet` produced, recovered from
its bytecode — struct formats `<HB`/`<BHBBIH`/`<BB`/`<Bf`/`<B` in field order
ServiceID, Version, DateTimeNs, ControllerIndex, BitRate, PacketType,
PacketData) and asserts the encoder matches it bit-for-bit.
"""
import struct
from datetime import datetime, timezone

import pytest

from pybluehost.sniffer.ellisys import encode_ellisys_injection_packet


def test_encode_hci_reset_command_layout():
    """HCI Reset command (opcode 0x0C03, len 0x00) injected at a fixed time."""
    # Fixed wall clock: 2026-01-15 00:00:01.000000 UTC
    wall = datetime(2026, 1, 15, 0, 0, 1, 0, tzinfo=timezone.utc)
    hci_payload = bytes.fromhex("03 0C 00")  # HCI_Reset opcode + len
    pkt = encode_ellisys_injection_packet(
        wall_clock=wall,
        bit_rate=12_000_000.0,
        packet_type=0x01,           # Ellisys Command
        hci_payload=hci_payload,
        controller_index=0,
    )

    # Header: Service ID 0x0002 (LE) + Version 0x01
    assert pkt[0:3] == b"\x02\x00\x01"

    # Object 0x02 DateTimeNs (tag) + year 2026 (LE) + month 1 + day 15
    # + ns_low (LE u32) + ns_high (LE u16)
    # ns at 00:00:01.000000 = 1_000_000_000 ns
    ns = 1_000_000_000
    ns_low = ns & 0xFFFFFFFF
    ns_high = (ns >> 32) & 0xFFFF
    expected_datetime = (
        b"\x02"                                   # tag
        + (2026).to_bytes(2, "little")             # year
        + bytes([1, 15])                           # month, day
        + ns_low.to_bytes(4, "little")
        + ns_high.to_bytes(2, "little")
    )
    assert pkt[3:14] == expected_datetime

    # Object 0x83 controller index 0
    assert pkt[14:16] == b"\x83\x00"

    # Object 0x80 bit rate float32 LE = 12_000_000.0
    assert pkt[16:21] == b"\x80" + struct.pack("<f", 12_000_000.0)

    # Object 0x81 packet type Command (0x01)
    assert pkt[21:23] == b"\x81\x01"

    # Object 0x82 packet data tag + payload
    assert pkt[23:] == b"\x82" + hci_payload


def test_encode_matches_canonical_demo_layout():
    """Independent golden cross-check against the demo's exact byte layout.

    Rebuilds the expected packet with the recovered demo field order /
    struct formats and asserts the encoder is byte-identical. Guards against
    any future drift in the encoder.
    """
    wall = datetime(2026, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc)
    hci = bytes.fromhex("03 0C 00")
    bit_rate = 12_000_000.0
    packet_type = 0x01  # Command

    # ns since UTC midnight
    ns = (((12 * 60 + 30) * 60 + 45) * 1_000_000_000) + 123456 * 1_000
    expected = b"".join([
        struct.pack("<HB", 0x0002, 0x01),                       # ServiceID, Version
        struct.pack("<BHBBIH", 0x02, 2026, 1, 15,
                    ns & 0xFFFFFFFF, (ns >> 32) & 0xFFFF),       # DateTimeNs
        struct.pack("<BB", 0x83, 0),                            # ControllerIndex
        struct.pack("<Bf", 0x80, bit_rate),                    # BitRate
        struct.pack("<BB", 0x81, packet_type),                 # PacketType
        struct.pack("<B", 0x82),                               # PacketData tag
        hci,
    ])

    produced = encode_ellisys_injection_packet(
        wall_clock=wall, bit_rate=bit_rate,
        packet_type=packet_type, hci_payload=hci, controller_index=0,
    )
    assert produced == expected
