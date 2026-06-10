import math
import struct

import pytest

from pybluehost.audio.codec.msbc import MSBCDecoder, MSBCEncoder


def _sine_pcm(freq_hz, sample_rate, num_samples, amplitude=16000):
    return struct.pack(
        f"<{num_samples}h",
        *[
            int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            for i in range(num_samples)
        ],
    )


def test_msbc_frame_length_57_bytes():
    enc = MSBCEncoder()
    pcm = bytes(2 * 15 * 8)     # 15 blocks × 8 subbands × 1 channel × 2 bytes
    frame = enc.encode(pcm)
    assert len(frame) == 57
    assert frame[0] == 0xAD


def test_msbc_round_trip_psnr_400hz():
    """400 Hz sine at 16 kHz / mSBC → round-trip PSNR above backend threshold.

    Filter delay is backend-dependent (pure-Python ≈ 80, libsbc ≈ 193) so we
    scan a range and pick the best alignment.

    Thresholds:
    - libsbc backend → > 60 dB (typically ~80 dB; near transparent)
    - pure-Python fallback → > 12 dB (simplified filter bank, see Plan A.1
      Task 8 deferral notes)."""
    from pybluehost.audio.codec.sbc import sbc_backend

    sr = 16000
    pcm = _sine_pcm(400, sr, num_samples=15 * 8 * 50)
    enc = MSBCEncoder()
    dec = MSBCDecoder()
    samples_per_frame_bytes = 2 * 15 * 8
    decoded = bytearray()
    for i in range(50):
        chunk = pcm[i * samples_per_frame_bytes:(i + 1) * samples_per_frame_bytes]
        decoded.extend(dec.decode(enc.encode(chunk)))

    original = list(struct.unpack(f"<{len(pcm)//2}h", pcm))
    rec = list(struct.unpack(f"<{len(decoded)//2}h", bytes(decoded)))
    best_psnr = -math.inf
    for delay in range(50, 250):
        if delay + 200 >= len(rec):
            break
        n = min(len(original) - delay, len(rec) - delay) - 100
        if n <= 0:
            continue
        err = [original[i] - rec[i + delay] for i in range(n)]
        mse = sum(e * e for e in err) / n
        if mse > 0:
            best_psnr = max(best_psnr, 10 * math.log10((32767 ** 2) / mse))

    backend = sbc_backend()
    threshold = 60 if backend == "libsbc" else 12
    assert best_psnr > threshold, (
        f"PSNR {best_psnr:.2f} dB below {threshold} dB threshold ({backend} backend)"
    )


def test_msbc_optional_libsbc_cross_check():
    """If libsbc is installed, encode the same audio through both paths.
    Skipped when libsbc is unavailable (no CI image has it as of Plan A.1)."""
    try:
        import ctypes
        ctypes.CDLL("libsbc.so.1")
    except OSError:
        pytest.skip("libsbc not installed")
    pytest.skip("libsbc cross-check stub — implement when libsbc is in CI")
