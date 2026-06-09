import pytest

from pybluehost.audio.codec.sbc import SBCHeader


def test_sbc_header_round_trip_a2dp_default():
    """A2DP default: 44.1kHz / 16 blocks / joint-stereo / loudness / 8 subbands / bitpool 53."""
    hdr = SBCHeader(
        sample_rate=44100, blocks=16, channel_mode="joint_stereo",
        allocation="loudness", subbands=8, bitpool=53,
    )
    raw = hdr.to_bytes(payload_for_crc=b"")
    assert raw[0] == 0x9C
    parsed = SBCHeader.from_bytes(raw + b"\x00" * 80)
    assert parsed.sample_rate == 44100
    assert parsed.blocks == 16
    assert parsed.channel_mode == "joint_stereo"
    assert parsed.allocation == "loudness"
    assert parsed.subbands == 8
    assert parsed.bitpool == 53


def test_sbc_header_msbc_preset():
    """mSBC uses blocks=15 which is NOT in the standard _BLOCKS table.
    The mSBC envelope (syncword 0xAD + blocks=15) lives in Task 10's wrapper,
    not in the standard SBC header parser.
    """
    pytest.skip("mSBC blocks=15 deferred to Task 10 wrapper")


def test_sbc_header_invalid_syncword():
    with pytest.raises(ValueError, match="syncword"):
        SBCHeader.from_bytes(b"\x9D\x00\x00\x00")


def test_sbc_header_invalid_bitpool_range():
    with pytest.raises(ValueError, match="bitpool"):
        SBCHeader(sample_rate=44100, blocks=16, channel_mode="stereo",
                  allocation="loudness", subbands=8, bitpool=300)


def test_sbc_header_invalid_blocks_value():
    with pytest.raises(ValueError, match="blocks"):
        SBCHeader(sample_rate=44100, blocks=20, channel_mode="stereo",
                  allocation="loudness", subbands=8, bitpool=53)


def test_sbc_header_frame_length_calc():
    """For A2DP default (joint_stereo / 16 blocks / 8 subbands / bitpool 53), frame = 119 bytes.

    Walk-through:
      channels = 2 (joint_stereo)
      nb = subbands * channels = 8 * 2 = 16
      scale_factor_bytes = ceil(16/2) = 8
      data_bits = 16 * 53 + 8 (join bits) = 856
      data_bytes = ceil(856/8) = 107
      total = 4 + 8 + 107 = 119
    """
    hdr = SBCHeader(sample_rate=44100, blocks=16, channel_mode="joint_stereo",
                    allocation="loudness", subbands=8, bitpool=53)
    assert hdr.frame_length() == 119
