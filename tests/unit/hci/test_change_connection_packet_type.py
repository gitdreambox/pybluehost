"""HCI_Change_Connection_Packet_Type command + Connection_Packet_Type_Changed event.

Wire layout per Bluetooth Core Spec 5.4 Vol 4 Part E §7.1.14 (command)
and §7.7.29 (event). Pay attention to the BR-vs-EDR inversion: BR bits
mean "allowed when set", EDR bits mean "disallowed when set".
"""
from __future__ import annotations

import pytest

from pybluehost.hci.constants import (
    HCI_CHANGE_CONNECTION_PACKET_TYPE,
    ClassicPacketType,
    EventCode,
)
from pybluehost.hci.packets import (
    ConnectionPacketTypeChanged,
    HCI_Change_Connection_Packet_Type,
    decode_hci_packet,
    parse_connection_packet_type_changed,
)


def test_opcode_value():
    # OGF 0x01 (Link Control) << 10 | OCF 0x0F = 0x040F
    assert HCI_CHANGE_CONNECTION_PACKET_TYPE == 0x040F


def test_event_code_value():
    assert EventCode.CONNECTION_PACKET_TYPE_CHANGED == 0x1D


def test_packet_type_bit_layout():
    # Sanity check the spec quirk so future operators can't get it wrong
    # without the test failing first.
    assert ClassicPacketType.DM1 == 0x0008
    assert ClassicPacketType.DH1 == 0x0010
    assert ClassicPacketType.DH3 == 0x0800
    assert ClassicPacketType.DH5 == 0x8000
    # EDR bits are "shall NOT be used" — set bit DISABLES that EDR type.
    assert ClassicPacketType.TWO_DH1_DISALLOW == 0x0002
    assert ClassicPacketType.THREE_DH1_DISALLOW == 0x0004


def test_aggregate_masks_consistent_with_individual_bits():
    assert ClassicPacketType.ALL_BR == (
        ClassicPacketType.DM1 | ClassicPacketType.DH1
        | ClassicPacketType.DM3 | ClassicPacketType.DH3
        | ClassicPacketType.DM5 | ClassicPacketType.DH5
    )
    assert ClassicPacketType.ALL_2DH_DISALLOW == (
        ClassicPacketType.TWO_DH1_DISALLOW
        | ClassicPacketType.TWO_DH3_DISALLOW
        | ClassicPacketType.TWO_DH5_DISALLOW
    )
    assert ClassicPacketType.ALL_3DH_DISALLOW == (
        ClassicPacketType.THREE_DH1_DISALLOW
        | ClassicPacketType.THREE_DH3_DISALLOW
        | ClassicPacketType.THREE_DH5_DISALLOW
    )


def test_encode_default_mask_let_controller_choose():
    cmd = HCI_Change_Connection_Packet_Type(
        connection_handle=0x0040,
        packet_type=ClassicPacketType.ALL_BR,  # only BR allowed, EDR auto
    )
    data = cmd.to_bytes()
    assert data[0] == 0x01           # H4 command
    assert data[1:3] == bytes([0x0F, 0x04])  # opcode LE
    assert data[3] == 4              # parameter length (handle 2 + mask 2)
    assert data[4:6] == bytes([0x40, 0x00])
    # mask = 0xCC18 (DM1|DH1|DM3|DH3|DM5|DH5)
    assert data[6:8] == bytes([0x18, 0xCC])


def test_encode_force_2dh_only():
    # 2-DH only: BR disallowed (no allow bits set), 3-DH disallowed.
    mask = ClassicPacketType.ALL_3DH_DISALLOW
    cmd = HCI_Change_Connection_Packet_Type(
        connection_handle=0x0010, packet_type=mask,
    )
    data = cmd.to_bytes()
    # 3-DH disallow bits only: 0x0004 | 0x0200 | 0x2000 = 0x2204
    assert data[6:8] == bytes([0x04, 0x22])


def test_decode_roundtrip():
    raw = bytes([
        0x01, 0x0F, 0x04, 0x04,        # cmd, opcode LE, length 4
        0x40, 0x00,                    # handle 0x0040
        0x04, 0x22,                    # mask = 0x2204 (3-DH disallow)
    ])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_Change_Connection_Packet_Type)
    assert pkt.connection_handle == 0x0040
    assert pkt.packet_type == 0x2204


def test_parse_event_2dh_negotiated():
    # status=0, handle=0x0040, mask=0x2204 (BR off, 2-DH allowed, 3-DH off)
    body = bytes([0x00, 0x40, 0x00, 0x04, 0x22])
    parsed = parse_connection_packet_type_changed(body)
    assert parsed == ConnectionPacketTypeChanged(
        status=0, connection_handle=0x0040, packet_type=0x2204,
    )


def test_parse_event_failure_status_preserved():
    # status=0x12 (Invalid HCI Command Parameters) — peer might have refused.
    body = bytes([0x12, 0x40, 0x00, 0x18, 0xCC])
    parsed = parse_connection_packet_type_changed(body)
    assert parsed.status == 0x12
    assert parsed.connection_handle == 0x0040
    # Stack should surface what packet types are currently in effect,
    # even on failure paths.
    assert parsed.packet_type == 0xCC18


def test_parse_event_short_payload_raises():
    with pytest.raises(ValueError):
        parse_connection_packet_type_changed(bytes([0x00, 0x40, 0x00]))
