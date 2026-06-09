import math

import pytest

from pybluehost.audio.codec.sbc import _analysis_filter_8


def _sine_pcm(freq_hz: float, sample_rate: int, num_samples: int, amplitude: int = 16000) -> list[int]:
    """Generate a mono int16-range sine, return list[int]."""
    return [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(num_samples)
    ]


def test_analysis_filter_8_energy_in_correct_subband_for_low_tone():
    """A 1 kHz sine at 44.1 kHz / 8 subbands → subband 0 is the peak
    (subband 0 covers roughly 0 .. Fs/16 ≈ 0..2756 Hz).

    Real SBC analysis has finite stop-band attenuation; some energy leaks
    into adjacent bands. We assert subband 0 is the peak and at least 1.5x
    the next-highest band — consistent with the spec's filter response.
    """
    sr = 44100
    pcm = _sine_pcm(1000, sr, num_samples=32 * 8)   # 32 blocks; later blocks are post-warmup
    samples = _analysis_filter_8(pcm)                # shape: (blocks, 8)
    # Sum |sample| per subband, excluding the first 8 blocks (warmup transient).
    energies = [sum(abs(samples[b][sb]) for b in range(8, len(samples))) for sb in range(8)]
    peak = energies.index(max(energies))
    assert peak == 0, f"expected subband 0 peak, got {peak}, energies={energies}"
    runner_up = max(energies[1:])
    assert energies[0] > 1.5 * runner_up, (
        f"subband 0 ({energies[0]}) should dominate runner-up ({runner_up}); energies={energies}"
    )


def test_analysis_filter_8_high_tone_in_high_subband():
    """A 12 kHz sine at 44.1 kHz / 8 subbands → energy mostly in a high subband.
    12 kHz / (44100/16) ≈ 4.35, so band 3 or 4 should dominate."""
    sr = 44100
    pcm = _sine_pcm(12000, sr, num_samples=32 * 8)
    samples = _analysis_filter_8(pcm)
    energies = [sum(abs(samples[b][sb]) for b in range(8, len(samples))) for sb in range(8)]
    peak = energies.index(max(energies))
    assert peak in (3, 4), f"expected high-subband peak (3 or 4), got subband {peak}, energies={energies}"


def test_analysis_filter_8_silence_yields_zero():
    pcm = [0] * (16 * 8)
    samples = _analysis_filter_8(pcm)
    for block in samples:
        for v in block:
            assert v == 0


def test_analysis_filter_8_rejects_non_multiple_of_8():
    with pytest.raises(ValueError, match="multiple of 8"):
        _analysis_filter_8([0] * 13)
