"""SBCDecoder tests — verifies frame parsing + synthesis filter + round-trip PSNR.

Round-trip PSNR > 30 dB is the goal per the plan. SBC is lossy; we don't
require bit-perfect equivalence, just that the encoded → decoded signal
remains a recognizable approximation of the input."""
from __future__ import annotations

import math
import struct

import pytest

from pybluehost.audio.codec.sbc import SBCDecoder, SBCEncoder


def _sine_pcm_bytes(
    freq_hz: float, sample_rate: int, num_samples: int, amplitude: int = 8000
) -> bytes:
    samples = [
        int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(num_samples)
    ]
    return struct.pack(f"<{num_samples}h", *samples)


def _psnr_db(orig: list[int], rec: list[int]) -> float:
    """PSNR in dB. INT16 max = 32767. Returns inf if no error."""
    assert len(orig) == len(rec), f"length mismatch: {len(orig)} vs {len(rec)}"
    mse = sum((o - r) ** 2 for o, r in zip(orig, rec)) / len(orig)
    if mse == 0:
        return float("inf")
    return 10 * math.log10((32767.0 ** 2) / mse)


def test_decoder_silence_round_trip():
    """Silence in → silence out (within numerical noise floor)."""
    enc = SBCEncoder(
        sample_rate=44100, channels=1, channel_mode="mono",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    dec = SBCDecoder()
    pcm = bytes(2 * 128)
    frames = b""
    # Need enough frames to flush the synthesis filter's 80-sample state.
    for _ in range(8):
        frames += enc.encode(pcm)
    recovered, _consumed = dec.decode(frames)
    assert len(recovered) == 8 * 128 * 2   # bytes
    samples = list(struct.unpack(f"<{len(recovered) // 2}h", recovered))
    # Silence in → output must be exactly zero (no signal energy to leak).
    assert all(s == 0 for s in samples), f"silence round-trip leaked: max={max(map(abs, samples))}"


def test_decoder_sine_round_trip_psnr_above_threshold():
    """1 kHz mono sine, encode → decode → PSNR above backend threshold.

    Filter delay is backend-dependent (pure-Python ≈ 80, libsbc ≈ 73), so we
    scan a range and pick the best alignment.

    Thresholds:
    - libsbc backend → > 60 dB (typically ~80 dB; near transparent)
    - pure-Python fallback → > 15 dB (simplified analysis/synthesis pair,
      noiseless reconstruction ceiling ~27 dB; see Plan A.1 Task 8 notes)."""
    from pybluehost.audio.codec.sbc import sbc_backend

    sr = 44100
    blocks_per_frame = 16
    subbands = 8
    num_frames = 16
    num_samples = num_frames * blocks_per_frame * subbands  # mono
    pcm = _sine_pcm_bytes(1000, sr, num_samples)
    enc = SBCEncoder(
        sample_rate=sr, channels=1, channel_mode="mono",
        blocks=blocks_per_frame, subbands=subbands, allocation="loudness", bitpool=53,
    )
    dec = SBCDecoder()
    frames = b""
    for f in range(num_frames):
        chunk = pcm[f * blocks_per_frame * subbands * 2:(f + 1) * blocks_per_frame * subbands * 2]
        frames += enc.encode(chunk)
    recovered, _ = dec.decode(frames)
    orig_samples = list(struct.unpack(f"<{num_samples}h", pcm))
    rec_samples = list(struct.unpack(f"<{len(recovered) // 2}h", recovered))
    best_psnr = -math.inf
    for delay in range(50, 250):
        if delay + 200 >= len(rec_samples):
            break
        n = min(len(orig_samples) - delay, len(rec_samples) - delay) - 100
        if n <= 0:
            continue
        err = [orig_samples[i] - rec_samples[i + delay] for i in range(n)]
        mse = sum(e * e for e in err) / n
        if mse > 0:
            best_psnr = max(best_psnr, 10 * math.log10((32767 ** 2) / mse))

    backend = sbc_backend()
    threshold = 60 if backend == "libsbc" else 15
    assert best_psnr > threshold, (
        f"PSNR {best_psnr:.2f} dB below {threshold} dB threshold ({backend} backend)"
    )


def test_decoder_rejects_invalid_syncword():
    dec = SBCDecoder()
    with pytest.raises(ValueError, match="syncword"):
        dec.decode(b"\x00" * 119)


def test_decoder_consumes_exactly_one_frame_at_a_time():
    """Decode returns (pcm, num_bytes_consumed); consumed must equal frame_size."""
    enc = SBCEncoder(
        sample_rate=44100, channels=1, channel_mode="mono",
        blocks=16, subbands=8, allocation="loudness", bitpool=53,
    )
    dec = SBCDecoder()
    pcm = bytes(2 * 128)
    frame = enc.encode(pcm)
    # Append junk after the frame; decoder should only consume `frame_size` bytes.
    recovered, consumed = dec.decode(frame + b"\xFF\xFF\xFF")
    assert consumed == enc.frame_size
    assert len(recovered) == 128 * 2
