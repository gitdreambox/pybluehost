import pytest

from pybluehost.avctp.constants import (
    AVCTPMessageDirection, AVCTPPacketType, AVRCP_PROFILE_UUID,
)
from pybluehost.avctp.message import AVCTPMessage


def test_single_command_to_bytes():
    msg = AVCTPMessage(
        transaction_label=0x5,
        packet_type=AVCTPPacketType.SINGLE,
        cr=AVCTPMessageDirection.COMMAND,
        ipid=0,
        profile_id=AVRCP_PROFILE_UUID,
        payload=b"\xAA\xBB",
    )
    # byte 0: 0x5<<4 | 0<<2 | 0<<1 | 0 = 0x50
    # bytes 1-2: 0x110E (big-endian) = [0x11, 0x0E]
    # payload: [0xAA, 0xBB]
    assert msg.to_bytes() == bytes([0x50, 0x11, 0x0E, 0xAA, 0xBB])


def test_single_response_no_payload():
    msg = AVCTPMessage(
        transaction_label=0xF,
        packet_type=AVCTPPacketType.SINGLE,
        cr=AVCTPMessageDirection.RESPONSE,
        ipid=0,
        profile_id=AVRCP_PROFILE_UUID,
        payload=b"",
    )
    # byte 0: 0xF<<4 | 0<<2 | 1<<1 | 0 = 0xF2
    assert msg.to_bytes() == bytes([0xF2, 0x11, 0x0E])


def test_ipid_response_bit():
    """If IPID is set, peer rejected the profile_id — bit is in byte 0 LSB."""
    msg = AVCTPMessage(
        transaction_label=0x3,
        packet_type=AVCTPPacketType.SINGLE,
        cr=AVCTPMessageDirection.RESPONSE,
        ipid=1,
        profile_id=0xDEAD,
        payload=b"",
    )
    # byte 0: 0x3<<4 | 0<<2 | 1<<1 | 1 = 0x33
    assert msg.to_bytes() == bytes([0x33, 0xDE, 0xAD])


def test_from_bytes_round_trip_command():
    raw = bytes([0x50, 0x11, 0x0E, 0xAA, 0xBB])
    msg = AVCTPMessage.from_bytes(raw)
    assert msg.transaction_label == 5
    assert msg.packet_type == AVCTPPacketType.SINGLE
    assert msg.cr == AVCTPMessageDirection.COMMAND
    assert msg.ipid == 0
    assert msg.profile_id == AVRCP_PROFILE_UUID
    assert msg.payload == bytes([0xAA, 0xBB])


def test_from_bytes_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        AVCTPMessage.from_bytes(b"\x50\x11")    # missing low byte of profile_id


def test_to_bytes_validates_transaction_label():
    msg = AVCTPMessage(
        transaction_label=0x20,    # > 15
        packet_type=AVCTPPacketType.SINGLE,
        cr=AVCTPMessageDirection.COMMAND,
        ipid=0, profile_id=0x110E, payload=b"",
    )
    with pytest.raises(ValueError, match="transaction_label"):
        msg.to_bytes()


def test_continue_packet_round_trip():
    """CONTINUE packets carry only TID/PT/CR — no profile_id."""
    msg = AVCTPMessage(
        transaction_label=0x7,
        packet_type=AVCTPPacketType.CONTINUE,
        cr=AVCTPMessageDirection.COMMAND,
        ipid=0, profile_id=0, payload=b"\xCC\xDD",
    )
    raw = msg.to_bytes()
    # byte 0: 0x7<<4 | 2<<2 | 0<<1 | 0 = 0x78
    # then payload bytes only
    assert raw == bytes([0x78, 0xCC, 0xDD])
    decoded = AVCTPMessage.from_bytes(raw)
    assert decoded.transaction_label == 7
    assert decoded.packet_type == AVCTPPacketType.CONTINUE
    assert decoded.cr == AVCTPMessageDirection.COMMAND
    assert decoded.profile_id == 0
    assert decoded.payload == b"\xCC\xDD"


def test_end_packet_round_trip():
    msg = AVCTPMessage(
        transaction_label=0x9,
        packet_type=AVCTPPacketType.END,
        cr=AVCTPMessageDirection.RESPONSE,
        ipid=0, profile_id=0, payload=b"\xEE",
    )
    raw = msg.to_bytes()
    # byte 0: 0x9<<4 | 3<<2 | 1<<1 | 0 = 0x9E
    assert raw == bytes([0x9E, 0xEE])
    decoded = AVCTPMessage.from_bytes(raw)
    assert decoded.packet_type == AVCTPPacketType.END
    assert decoded.cr == AVCTPMessageDirection.RESPONSE
    assert decoded.payload == b"\xEE"


def test_start_packet_round_trip():
    """START packets carry num_packets byte + profile_id + payload."""
    msg = AVCTPMessage(
        transaction_label=0x2,
        packet_type=AVCTPPacketType.START,
        cr=AVCTPMessageDirection.COMMAND,
        ipid=0, profile_id=AVRCP_PROFILE_UUID,
        payload=b"\x11\x22", num_packets=3,
    )
    raw = msg.to_bytes()
    # byte 0: 0x2<<4 | 1<<2 | 0<<1 | 0 = 0x24
    # byte 1: num_packets=3
    # bytes 2-3: profile_id = 0x110E BE
    # bytes 4+: payload
    assert raw == bytes([0x24, 0x03, 0x11, 0x0E, 0x11, 0x22])
    decoded = AVCTPMessage.from_bytes(raw)
    assert decoded.packet_type == AVCTPPacketType.START
    assert decoded.num_packets == 3
    assert decoded.profile_id == AVRCP_PROFILE_UUID
    assert decoded.payload == b"\x11\x22"


def test_start_packet_validates_num_packets():
    """START packets require 1..255 num_packets per AVCTP v1.4 §6.3."""
    msg = AVCTPMessage(
        transaction_label=0x1, packet_type=AVCTPPacketType.START,
        cr=AVCTPMessageDirection.COMMAND, ipid=0,
        profile_id=AVRCP_PROFILE_UUID, payload=b"\x00", num_packets=0,
    )
    with pytest.raises(ValueError, match="num_packets"):
        msg.to_bytes()
