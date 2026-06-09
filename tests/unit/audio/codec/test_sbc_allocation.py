import pytest

from pybluehost.audio.codec.sbc import (
    _bit_allocation_loudness,
    _compute_scale_factors,
)


def test_scale_factors_constant_signal():
    """Magnitude 100 → bit_length(100) = 7."""
    blocks = [[100] * 8 for _ in range(16)]   # 16 blocks, 8 subbands, mono
    sf = _compute_scale_factors(blocks, channels=1)
    assert all(v == 7 for v in sf[0]), f"sf[0]={sf[0]}"


def test_scale_factors_zero_signal():
    blocks = [[0] * 8 for _ in range(16)]
    sf = _compute_scale_factors(blocks, channels=1)
    assert all(v == 0 for v in sf[0])


def test_scale_factors_stereo():
    """For stereo, interleaved subband samples: row[sb * channels + ch]."""
    # 1 channel, 8 subbands, mono — sample[0..7].
    # Stereo: sample[0..15], where (sb, ch) maps to sb*2 + ch.
    blocks = [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 50, 200] for _ in range(8)]
    # subband 7 channel 0 = 50 (sf = 6); subband 7 channel 1 = 200 (sf = 8)
    sf = _compute_scale_factors(blocks, channels=2)
    assert sf[0][7] == 50 .bit_length()    # 6
    assert sf[1][7] == 200 .bit_length()   # 8


def test_bit_allocation_loudness_44100_distributes_bitpool():
    """A2DP default ish config: bitpool=53, 8 subbands, 44.1kHz, loudness."""
    # 1 channel, 8 subbands. Higher scale factors should get more bits.
    sf = [[7, 6, 5, 4, 3, 2, 1, 0]]
    bits = _bit_allocation_loudness(sf, bitpool=53, sample_rate=44100, subbands=8)
    # Total bits allocated per channel ≤ bitpool.
    assert sum(bits[0]) <= 53
    # Subbands with higher scale factors get at least as many bits as lower ones.
    # (Strict monotonicity may not hold due to loudness offset asymmetries; but
    # the highest-SF band gets ≥ the lowest-SF band's bits.)
    assert bits[0][0] >= bits[0][-1]


def test_bit_allocation_loudness_zero_signal_returns_zero_bits():
    sf = [[0] * 8]
    bits = _bit_allocation_loudness(sf, bitpool=53, sample_rate=44100, subbands=8)
    assert all(b == 0 for b in bits[0])


def test_bit_allocation_loudness_total_bits_does_not_exceed_bitpool():
    """For any reasonable scale factor distribution, allocated total ≤ bitpool."""
    sf = [[5, 5, 5, 5, 5, 5, 5, 5]]
    bits = _bit_allocation_loudness(sf, bitpool=30, sample_rate=44100, subbands=8)
    assert sum(bits[0]) <= 30


def test_bit_allocation_loudness_invalid_sample_rate_raises():
    sf = [[0] * 8]
    with pytest.raises(ValueError, match="sample_rate"):
        _bit_allocation_loudness(sf, bitpool=53, sample_rate=22050, subbands=8)
