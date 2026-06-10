import pytest

from pybluehost.avdtp.constants import (
    AVDTPMessageType, AVDTPPacketType, AVDTPSignalID,
)
from pybluehost.avdtp.signaling import AVDTPMessage


def test_single_command_to_bytes():
    msg = AVDTPMessage(
        transaction_id=0x5,
        packet_type=AVDTPPacketType.SINGLE,
        message_type=AVDTPMessageType.COMMAND,
        signal_id=AVDTPSignalID.DISCOVER,
        payload=b"",
    )
    # byte 0: 0x5 << 4 | 0 << 2 | 0 = 0x50
    # byte 1: 0x01 (signal id, RFA=00)
    assert msg.to_bytes() == bytes([0x50, 0x01])


def test_single_response_with_payload():
    payload = bytes([0x04, 0x00, 0x08, 0x00])   # 2 SEPs: seid=1 SRC + seid=2 SRC (encoded later)
    msg = AVDTPMessage(
        transaction_id=0xF,
        packet_type=AVDTPPacketType.SINGLE,
        message_type=AVDTPMessageType.RESPONSE_ACCEPT,
        signal_id=AVDTPSignalID.DISCOVER,
        payload=payload,
    )
    # byte 0: 0xF << 4 | 0 << 2 | 2 = 0xF2
    expected = bytes([0xF2, 0x01]) + payload
    assert msg.to_bytes() == expected


def test_from_bytes_round_trip_command():
    raw = bytes([0x50, 0x01])
    msg = AVDTPMessage.from_bytes(raw)
    assert msg.transaction_id == 5
    assert msg.packet_type == AVDTPPacketType.SINGLE
    assert msg.message_type == AVDTPMessageType.COMMAND
    assert msg.signal_id == AVDTPSignalID.DISCOVER
    assert msg.payload == b""


def test_from_bytes_round_trip_response_with_payload():
    raw = bytes([0xF2, 0x01, 0xAA, 0xBB, 0xCC])
    msg = AVDTPMessage.from_bytes(raw)
    assert msg.transaction_id == 15
    assert msg.message_type == AVDTPMessageType.RESPONSE_ACCEPT
    assert msg.signal_id == AVDTPSignalID.DISCOVER
    assert msg.payload == bytes([0xAA, 0xBB, 0xCC])


def test_from_bytes_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        AVDTPMessage.from_bytes(b"\x50")


def test_signal_id_masks_rfa_bits():
    """Decoder must ignore the high 2 bits (RFA) of byte 1."""
    # Set RFA bits high; signal ID stays = 0x01
    raw = bytes([0x50, 0xC1])
    msg = AVDTPMessage.from_bytes(raw)
    assert msg.signal_id == AVDTPSignalID.DISCOVER
