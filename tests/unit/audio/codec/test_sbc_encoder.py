import pytest

from pybluehost.audio.codec.sbc import SBCEncoder


def test_encoder_default_a2dp_frame_length():
    """A2DP default: 44.1kHz / stereo / 16 blocks / joint-stereo / loudness / 8sb / bitpool 53.
    Frame must be exactly 119 bytes per A2DP v1.4 §B.2.4."""
    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="joint_stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    # 16 blocks × 8 subbands × 2 channels = 256 samples per frame, int16 LE
    pcm = bytes(2 * 256)  # silence (256 samples × 2 bytes)
    frame = enc.encode(pcm)
    assert len(frame) == 119
    assert frame[0] == 0x9C   # syncword


def test_encoder_rejects_wrong_pcm_length():
    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    with pytest.raises(ValueError, match="length"):
        enc.encode(b"\x00" * 100)


def test_encoder_silence_produces_zero_scale_factors():
    """Silent input → all scale factors 0 → scale factor bytes 0."""
    enc = SBCEncoder(
        sample_rate=44100, channels=1, channel_mode="mono",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    pcm = bytes(2 * 16 * 8)
    frame = enc.encode(pcm)
    # Header is bytes 0-3, scale factors follow. 8 subbands × 4 bits = 4 bytes.
    assert frame[4:8] == b"\x00\x00\x00\x00"


def test_encoder_mono_channel_mode_consistency_check():
    """channel_mode='mono' requires channels=1; mismatch raises."""
    with pytest.raises(ValueError, match="channel"):
        SBCEncoder(
            sample_rate=44100, channels=2, channel_mode="mono",
            blocks=16, subbands=8, allocation="loudness", bitpool=53,
        )


def test_encoder_stereo_channel_mode_consistency_check():
    with pytest.raises(ValueError, match="channel"):
        SBCEncoder(
            sample_rate=44100, channels=1, channel_mode="stereo",
            blocks=16, subbands=8, allocation="loudness", bitpool=53,
        )


def test_encoder_frame_size_attr():
    """SBCEncoder exposes frame_size for callers to know how big each frame will be."""
    enc = SBCEncoder(
        sample_rate=44100, channels=2, channel_mode="joint_stereo",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    assert enc.frame_size == 119


def test_encoder_non_silent_input_produces_nonzero_frame():
    """A real signal must produce a non-trivial frame (not all zeros after header)."""
    import math
    import struct
    enc = SBCEncoder(
        sample_rate=44100, channels=1, channel_mode="mono",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    # 1 kHz sine, 16 blocks × 8 subbands = 128 samples
    samples = [int(8000 * math.sin(2 * math.pi * 1000 * i / 44100)) for i in range(128)]
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    frame = enc.encode(pcm)
    # Frame size must match the header's computation
    assert len(frame) == enc.frame_size
    # Some scale factors should be non-zero (signal energy concentrates in low band)
    assert frame[4:8] != b"\x00\x00\x00\x00"
