import pytest

from pybluehost.avdtp.constants import (
    AVDTPMessageType, AVDTPPacketType, AVDTPSignalID,
    MediaType, ServiceCategory, TSEP,
)
from pybluehost.avdtp.signaling import (
    AVDTPMessage,
    decode_capabilities, decode_sep_descriptors, decode_seid_byte,
    encode_capabilities, encode_sep_descriptor, encode_seid_byte,
)


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


def test_encode_sep_descriptor_source_not_in_use():
    # seid=1, in_use=False, media=audio, tsep=SRC
    b = encode_sep_descriptor(seid=1, in_use=False, media_type=MediaType.AUDIO, tsep=TSEP.SRC)
    # byte 0: seid=1<<2 | in_use=0<<1 | RFA=0  = 0x04
    # byte 1: media=0<<4 | tsep=0<<3 | RFA=0   = 0x00
    assert b == bytes([0x04, 0x00])


def test_encode_sep_descriptor_sink_in_use():
    b = encode_sep_descriptor(seid=5, in_use=True, media_type=MediaType.AUDIO, tsep=TSEP.SNK)
    # byte 0: 5<<2 | 1<<1 | 0 = 0x16
    # byte 1: 0<<4 | 1<<3 | 0 = 0x08
    assert b == bytes([0x16, 0x08])


def test_decode_sep_descriptors_multiple():
    raw = bytes([0x04, 0x00, 0x16, 0x08])
    seps = decode_sep_descriptors(raw)
    assert len(seps) == 2
    assert seps[0] == (1, False, MediaType.AUDIO, TSEP.SRC)
    assert seps[1] == (5, True, MediaType.AUDIO, TSEP.SNK)


def test_decode_sep_descriptors_truncated_raises():
    with pytest.raises(ValueError, match="truncated"):
        decode_sep_descriptors(b"\x04")    # odd length


def test_encode_capabilities_media_transport_only():
    # Just media transport (LOSC=0)
    caps = [(ServiceCategory.MEDIA_TRANSPORT, b"")]
    b = encode_capabilities(caps)
    assert b == bytes([0x01, 0x00])


def test_encode_capabilities_with_sbc_codec():
    sbc_blob = bytes([0x00, 0x00, 0xFF, 0xFF])    # placeholder SBC blob (codec_type+specific)
    caps = [
        (ServiceCategory.MEDIA_TRANSPORT, b""),
        (ServiceCategory.MEDIA_CODEC, sbc_blob),
    ]
    b = encode_capabilities(caps)
    # [01, 00, 07, 04, 00, 00, FF, FF]
    assert b == bytes([0x01, 0x00, 0x07, 0x04]) + sbc_blob


def test_decode_capabilities_round_trip():
    sbc_blob = bytes([0x00, 0x00, 0xFF, 0xFF])
    original = [
        (ServiceCategory.MEDIA_TRANSPORT, b""),
        (ServiceCategory.MEDIA_CODEC, sbc_blob),
    ]
    decoded = decode_capabilities(encode_capabilities(original))
    assert decoded == original


def test_seid_byte_round_trip():
    assert encode_seid_byte(3) == 0x0C    # 3 << 2
    assert decode_seid_byte(0x0C) == 3
    assert encode_seid_byte(62) == 0xF8
    assert decode_seid_byte(0xF8) == 62
