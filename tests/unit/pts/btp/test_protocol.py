import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BtpFrame,
    BTP_HEADER_SIZE,
    decode_btp_frame,
    encode_btp_frame,
)


def test_header_size_is_5_bytes():
    assert BTP_HEADER_SIZE == 5


def test_frame_round_trip_empty_payload():
    frame = BtpFrame(
        service=op.SERVICE_CORE,
        opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=b"",
    )
    raw = encode_btp_frame(frame)
    assert raw == bytes([0x00, 0x02, 0xFF, 0x00, 0x00])
    parsed = decode_btp_frame(raw)
    assert parsed == frame


def test_frame_round_trip_with_data():
    payload = bytes(range(7))
    frame = BtpFrame(
        service=op.SERVICE_CORE,
        opcode=op.OP_CORE_REGISTER,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=payload,
    )
    raw = encode_btp_frame(frame)
    assert raw[0] == 0x00
    assert raw[1] == 0x03
    assert raw[2] == 0xFF
    assert raw[3:5] == (7).to_bytes(2, "little")
    assert raw[5:] == payload
    assert decode_btp_frame(raw) == frame


def test_frame_round_trip_max_length():
    """Max payload = 2^16 - 1 = 65535 bytes."""
    payload = bytes(65535)
    frame = BtpFrame(
        service=op.SERVICE_GAP, opcode=0x10,
        controller_index=0, data=payload,
    )
    raw = encode_btp_frame(frame)
    assert len(raw) == 5 + 65535
    assert decode_btp_frame(raw).data == payload


def test_encode_rejects_data_over_u16():
    with pytest.raises(ValueError, match="length"):
        encode_btp_frame(BtpFrame(
            service=op.SERVICE_CORE, opcode=0x05,
            controller_index=0xFF, data=bytes(70000),
        ))


def test_decode_rejects_truncated_header():
    with pytest.raises(ValueError, match="header"):
        decode_btp_frame(b"\x00\x01\xFF")


def test_decode_rejects_short_data():
    """Length says 10 bytes, only 3 provided."""
    raw = bytes([0x00, 0x01, 0xFF, 10, 0]) + b"\x01\x02\x03"
    with pytest.raises(ValueError, match="truncated"):
        decode_btp_frame(raw)


def test_decode_succeeds_on_exact_size():
    raw = bytes([0x00, 0x01, 0xFF, 3, 0]) + b"\x01\x02\x03"
    frame = decode_btp_frame(raw)
    assert frame.data == b"\x01\x02\x03"
