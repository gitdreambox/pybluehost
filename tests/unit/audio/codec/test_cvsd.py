import math
import struct

from pybluehost.audio.codec.cvsd import CVSDDecoder, CVSDEncoder


def _sine_pcm(freq_hz, sample_rate, num_samples, amplitude=16000):
    return struct.pack(
        f"<{num_samples}h",
        *[
            int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            for i in range(num_samples)
        ],
    )


def test_cvsd_round_trip_psnr_400hz():
    """400 Hz sine at 8 kHz / CVSD → round-trip PSNR > 25 dB after warm-up."""
    sr = 8000
    pcm = _sine_pcm(400, sr, num_samples=4000)   # 0.5 s

    enc = CVSDEncoder()
    dec = CVSDDecoder()
    encoded = enc.encode(pcm)
    recovered = dec.decode(encoded)

    original = list(struct.unpack(f"<{len(pcm)//2}h", pcm))
    rec = list(struct.unpack(f"<{len(recovered)//2}h", recovered))
    n = min(len(original), len(rec)) - 200    # skip warm-up
    err = [original[i + 200] - rec[i + 200] for i in range(n)]
    mse = sum(e * e for e in err) / n
    psnr = 10 * math.log10((32767 ** 2) / max(mse, 1))
    assert psnr > 25, f"PSNR {psnr:.2f} dB below 25 dB threshold"


def test_cvsd_encode_output_size():
    """N samples → ceil(N/8) bytes (1 bit per sample, packed MSB-first)."""
    enc = CVSDEncoder()
    pcm = bytes(2 * 16)            # 16 samples
    encoded = enc.encode(pcm)
    assert len(encoded) == 2       # 16 bits / 8 = 2 bytes


def test_cvsd_silence_round_trip_stays_near_zero():
    """Silence PCM in → encode → decode → output should track near zero.

    Note: the original plan tested "all-zero CVSD bytes → near-zero PCM", but
    that's algorithmically impossible — sustained zero bits force the decoder's
    estimate strictly downward. A silence ROUND-TRIP is the right test: the
    encoder sees PCM≈0, emits bits that oscillate around 0, and the decoder
    tracks back to near zero."""
    enc = CVSDEncoder()
    dec = CVSDDecoder()
    pcm_silence = bytes(2 * 512)   # 512 samples of int16 zero
    encoded = enc.encode(pcm_silence)
    decoded = dec.decode(encoded)
    samples = list(struct.unpack(f"<{len(decoded)//2}h", decoded))
    # After ~100 samples warmup, output should be within one MAX_STEP of zero.
    assert max(abs(s) for s in samples[100:]) < 5000
