import pytest

from pybluehost.classic.avdtp.media import AVDTPMediaPacket


def test_to_bytes_minimum_header():
    pkt = AVDTPMediaPacket(
        sequence_number=0x1234,
        timestamp=0x12345678,
        ssrc=0xDEADBEEF,
        payload=b"",
    )
    raw = pkt.to_bytes()
    # First byte: V=2 (10) | P=0 | X=0 | CC=0 = 0x80
    # Second byte: M=0 | PT=96 = 0x60
    assert raw[0] == 0x80
    assert raw[1] == 0x60
    assert raw[2:4] == b"\x12\x34"
    assert raw[4:8] == b"\x12\x34\x56\x78"
    assert raw[8:12] == b"\xDE\xAD\xBE\xEF"
    # 1-byte SBC frame count = 0
    assert raw[12:13] == b"\x00"
    assert len(raw) == 13


def test_to_bytes_with_sbc_payload():
    sbc_frame = bytes([0x9C] + [0x00] * 118)
    pkt = AVDTPMediaPacket(
        sequence_number=1,
        timestamp=128,
        ssrc=0xABCD1234,
        payload=sbc_frame * 2,
        frame_count=2,
    )
    raw = pkt.to_bytes()
    assert len(raw) == 12 + 1 + 119 * 2
    assert raw[12] == 2


def test_from_bytes_round_trip():
    sbc_frame = bytes([0x9C] + [0x00] * 118)
    original = AVDTPMediaPacket(
        sequence_number=42,
        timestamp=4096,
        ssrc=0x12345678,
        payload=sbc_frame * 3,
        frame_count=3,
    )
    decoded = AVDTPMediaPacket.from_bytes(original.to_bytes())
    assert decoded.sequence_number == original.sequence_number
    assert decoded.timestamp == original.timestamp
    assert decoded.ssrc == original.ssrc
    assert decoded.payload == original.payload
    assert decoded.frame_count == 3


def test_from_bytes_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        AVDTPMediaPacket.from_bytes(b"\x80\x60\x00")    # < 12 byte header


def test_from_bytes_wrong_version_raises():
    bad = bytes([0xC0, 0x60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])    # V=3
    with pytest.raises(ValueError, match="RTP version"):
        AVDTPMediaPacket.from_bytes(bad)
