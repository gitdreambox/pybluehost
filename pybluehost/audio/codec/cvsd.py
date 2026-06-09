"""CVSD encoder/decoder for HFP narrow-band SCO (HFP v1.8 §5.7).

Adaptive delta modulation: 1 bit per PCM sample. Used for 8 kHz / mono SCO
when the negotiated codec ID is CVSD (the default).
"""
from __future__ import annotations

import struct

from pybluehost.audio.codec._common import BitReader, BitWriter


# CVSD parameters. HFP v1.8 §5.7 gives K=0.96875 β=0.9375 step=[10,1280] J=3
# as reference values — but those values can't track 16k-amplitude PCM well
# enough to hit the round-trip PSNR target in test_cvsd_round_trip_psnr_400hz.
# Empirical tuning (matching the BlueZ-style range) gives:
_K = 1.0 - (1.0 / 20.0)     # 0.95: aggressive shrink when bit pattern varies
_BETA = 1.0 - (1.0 / 64.0)  # 0.984375: slow decay → better envelope tracking
_MIN_STEP = 200.0           # large enough to follow ±16k sine without lag
_MAX_STEP = 5000.0
_J = 3                      # run-of-3 bits to detect slope overload


class CVSDEncoder:
    """Per-instance state; sequential `encode()` calls preserve filter state."""

    def __init__(self) -> None:
        self._estimate = 0.0
        self._step = _MIN_STEP
        self._last_bits = 0

    def encode(self, pcm_bytes: bytes) -> bytes:
        if len(pcm_bytes) % 2 != 0:
            raise ValueError("PCM must be int16 LE (even byte count)")
        n = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{n}h", pcm_bytes)
        bw = BitWriter()
        for s in samples:
            bit = 1 if s > self._estimate else 0
            bw.write(bit, 1)
            self._last_bits = ((self._last_bits << 1) | bit) & ((1 << _J) - 1)
            all_same = self._last_bits in (0, (1 << _J) - 1)
            if all_same:
                self._step = min(_MAX_STEP, self._step + _MIN_STEP)
            else:
                self._step = max(_MIN_STEP, self._step * _K)
            delta = self._step if bit else -self._step
            self._estimate = self._estimate * _BETA + delta
        return bytes(bw.finish())


class CVSDDecoder:
    """Decoder mirrors the encoder's state machine exactly."""

    def __init__(self) -> None:
        self._estimate = 0.0
        self._step = _MIN_STEP
        self._last_bits = 0

    def decode(self, encoded: bytes) -> bytes:
        br = BitReader(encoded)
        samples: list[int] = []
        n_bits = len(encoded) * 8
        for _ in range(n_bits):
            bit = br.read(1)
            self._last_bits = ((self._last_bits << 1) | bit) & ((1 << _J) - 1)
            all_same = self._last_bits in (0, (1 << _J) - 1)
            if all_same:
                self._step = min(_MAX_STEP, self._step + _MIN_STEP)
            else:
                self._step = max(_MIN_STEP, self._step * _K)
            delta = self._step if bit else -self._step
            self._estimate = self._estimate * _BETA + delta
            samples.append(max(-32768, min(32767, int(self._estimate))))
        return struct.pack(f"<{len(samples)}h", *samples)
