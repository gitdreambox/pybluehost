"""SBC codec — A2DP §B encoder + decoder. Pure DSP, no Bluetooth deps."""
from __future__ import annotations

import math
from dataclasses import dataclass

from pybluehost.audio.codec._common import sbc_crc8


_SAMPLE_RATES = {16000: 0b00, 32000: 0b01, 44100: 0b10, 48000: 0b11}
_SAMPLE_RATES_INV = {v: k for k, v in _SAMPLE_RATES.items()}
_BLOCKS = {4: 0b00, 8: 0b01, 12: 0b10, 16: 0b11}
_BLOCKS_INV = {v: k for k, v in _BLOCKS.items()}
_CHANNEL_MODES = {
    "mono": 0b00, "dual": 0b01, "stereo": 0b10, "joint_stereo": 0b11,
}
_CHANNEL_MODES_INV = {v: k for k, v in _CHANNEL_MODES.items()}
_ALLOCATIONS = {"loudness": 0b0, "snr": 0b1}
_ALLOCATIONS_INV = {v: k for k, v in _ALLOCATIONS.items()}
_SUBBANDS = {4: 0b0, 8: 0b1}
_SUBBANDS_INV = {v: k for k, v in _SUBBANDS.items()}

_SYNCWORD = 0x9C


@dataclass(frozen=True)
class SBCHeader:
    """SBC frame header per A2DP v1.4 §B.2 (4 bytes: syncword + 2 packed bytes + CRC)."""

    sample_rate: int
    blocks: int
    channel_mode: str
    allocation: str
    subbands: int
    bitpool: int

    def __post_init__(self) -> None:
        if self.sample_rate not in _SAMPLE_RATES:
            raise ValueError(f"unsupported sample_rate {self.sample_rate}")
        if self.blocks not in _BLOCKS:
            raise ValueError(f"unsupported blocks={self.blocks}")
        if self.channel_mode not in _CHANNEL_MODES:
            raise ValueError(f"unknown channel_mode {self.channel_mode!r}")
        if self.allocation not in _ALLOCATIONS:
            raise ValueError(f"unknown allocation {self.allocation!r}")
        if self.subbands not in _SUBBANDS:
            raise ValueError(f"unsupported subbands={self.subbands}")
        if not (2 <= self.bitpool <= 250):
            raise ValueError(f"bitpool {self.bitpool} out of A2DP range 2..250")

    @property
    def channels(self) -> int:
        return 1 if self.channel_mode == "mono" else 2

    def frame_length(self) -> int:
        """A2DP v1.4 §B.2.4. Returns total frame length including the 4-byte header."""
        nb = self.subbands * self.channels
        scale_factor_bytes = math.ceil(nb / 2)
        if self.channel_mode == "mono":
            data_bits = self.blocks * self.bitpool
        elif self.channel_mode == "dual":
            data_bits = self.blocks * self.bitpool * 2
        elif self.channel_mode == "stereo":
            data_bits = self.blocks * self.bitpool
        else:  # joint_stereo
            data_bits = self.blocks * self.bitpool + self.subbands
        data_bytes = math.ceil(data_bits / 8)
        return 4 + scale_factor_bytes + data_bytes

    def to_bytes(self, *, payload_for_crc: bytes = b"") -> bytes:
        """Encode the 4-byte header. `payload_for_crc` is the CRC-covered region after
        bytes 1-2 (scale factors + join bits) when available."""
        b1 = (
            (_SAMPLE_RATES[self.sample_rate] << 6)
            | (_BLOCKS[self.blocks] << 4)
            | (_CHANNEL_MODES[self.channel_mode] << 2)
            | (_ALLOCATIONS[self.allocation] << 1)
            | _SUBBANDS[self.subbands]
        )
        b2 = self.bitpool & 0xFF
        crc_data = bytes([b1, b2]) + payload_for_crc
        crc = sbc_crc8(crc_data, num_bits=len(crc_data) * 8)
        return bytes([_SYNCWORD, b1, b2, crc])

    @classmethod
    def from_bytes(cls, data: bytes) -> "SBCHeader":
        if len(data) < 4:
            raise ValueError("data too short for SBC header (need ≥ 4 bytes)")
        if data[0] != _SYNCWORD:
            raise ValueError(f"bad syncword 0x{data[0]:02X}, expected 0x9C")
        b1 = data[1]
        bitpool = data[2]
        sr = _SAMPLE_RATES_INV[(b1 >> 6) & 0b11]
        blocks = _BLOCKS_INV[(b1 >> 4) & 0b11]
        chmode = _CHANNEL_MODES_INV[(b1 >> 2) & 0b11]
        alloc = _ALLOCATIONS_INV[(b1 >> 1) & 0b1]
        sb = _SUBBANDS_INV[b1 & 0b1]
        return cls(sample_rate=sr, blocks=blocks, channel_mode=chmode,
                   allocation=alloc, subbands=sb, bitpool=bitpool)


# 8-subband proto filter coefficients (80 taps) per A2DP v1.4 Table B.5.
# Source: nxp-upstream/libsbc encoder/srce/sbc_enc_coeffs.c gas32CoeffFor8SBs
# (Broadcom Apache 2.0 reference). Q31 fixed-point converted to float by /2^31.
_PROTO_FILTER_8 = (
    0.000000000000000, 0.000156575348228, 0.000343256164342, 0.000554619822651,
    0.000823919195682, 0.001139924861491, 0.001476401463151, 0.001783716958016,
    0.002011825330555, 0.002103719860315, 0.001994545105845, 0.001616562716663,
    0.000902154482901, -0.000178805086762, -0.001649730838835, -0.003497174475342,
    0.005659494549036, 0.008029411546886, 0.010458444245160, 0.012747233267874,
    0.014652526006103, 0.015904560219496, 0.016220846679062, 0.015318410471082,
    0.012937180232257, 0.008857575245202, 0.002924084197730, -0.004915779922158,
    -0.014640407171100, -0.026109875179827, -0.039075138047338, -0.053187302779406,
    0.067998942919075, 0.082984757609665, 0.097575391642749, 0.111196688842028,
    0.123264547903091, 0.133264414966106, 0.140753504820168, 0.145389846991748,
    0.146955067757517, 0.145389846991748, 0.140753504820168, 0.133264414966106,
    0.123264547903091, 0.111196688842028, 0.097575391642749, 0.082984757609665,
    -0.067998942919075, -0.053187302779406, -0.039075138047338, -0.026109875179827,
    -0.014640407171100, -0.004915779922158, 0.002924084197730, 0.008857575245202,
    0.012937180232257, 0.015318410471082, 0.016220846679062, 0.015904560219496,
    0.014652526006103, 0.012747233267874, 0.010458444245160, 0.008029411546886,
    -0.005659494549036, -0.003497174475342, -0.001649730838835, -0.000178805086762,
    0.000902154482901, 0.001616562716663, 0.001994545105845, 0.002103719860315,
    0.002011825330555, 0.001783716958016, 0.001476401463151, 0.001139924861491,
    0.000823919195682, 0.000554619822651, 0.000343256164342, 0.000156575348228,
)
assert len(_PROTO_FILTER_8) == 80

# Pre-computed analysis cosine matrix per A2DP v1.4 §B.5.
# M[k][i] = cos((2*k + 1) * (i - 4) * π / 16) for k in 0..7, i in 0..15.
_ANALYSIS_M_8 = tuple(
    tuple(math.cos((2 * k + 1) * (i - 4) * math.pi / 16.0) for i in range(16))
    for k in range(8)
)


def _analysis_filter_8(pcm: list[int]) -> list[list[int]]:
    """SBC 8-subband polyphase analysis filter per A2DP v1.4 §B.5.

    Input `pcm` is a flat list of int16 samples; length must be a multiple of 8.
    Returns nested list[blocks][subbands] of int (subband sample values).

    Stages:
      1. Slide 8 new PCM samples into an 80-sample window (newest at index 0).
      2. Multiply window by the 80-tap proto filter coefficients.
      3. Polyphase partial sums: Y[i] = sum(Z[i + 16j], j=0..4) for i in 0..15.
      4. Cosine modulation: S[k] = sum(M[k][i] * Y[i], i=0..15) for k in 0..7.
    """
    if len(pcm) % 8 != 0:
        raise ValueError("PCM length must be multiple of 8 for 8-subband filter")
    blocks = len(pcm) // 8
    window = [0] * 80
    result: list[list[int]] = []
    for block_idx in range(blocks):
        new_samples = pcm[block_idx * 8:(block_idx + 1) * 8]
        # Shift: newest 8 samples go at low indices, displacing old window.
        window = list(new_samples) + window[:72]
        # Windowing: Z[i] = C[i] * X[i]
        z = [window[i] * _PROTO_FILTER_8[i] for i in range(80)]
        # Polyphase partial sums: Y[i] = sum over j of Z[i + 16j], j=0..4
        y = [sum(z[i + 16 * j] for j in range(5)) for i in range(16)]
        # Cosine matrix: S[k] = sum over i of M[k][i] * Y[i]
        block_samples = []
        for k in range(8):
            s = sum(_ANALYSIS_M_8[k][i] * y[i] for i in range(16))
            block_samples.append(int(round(s)))
        result.append(block_samples)
    return result
