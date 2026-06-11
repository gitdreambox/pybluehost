"""SBC codec — A2DP §B encoder + decoder. Pure DSP, no Bluetooth deps."""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from pybluehost.audio.codec._common import BitReader, BitWriter, sbc_crc8


_SAMPLE_RATES = {16000: 0b00, 32000: 0b01, 44100: 0b10, 48000: 0b11}
_SAMPLE_RATES_INV = {v: k for k, v in _SAMPLE_RATES.items()}
_BLOCKS = {4: 0b00, 8: 0b01, 12: 0b10, 16: 0b11, 15: 0b11}
# Decode-side mapping. 0b11 is overloaded: standard SBC uses it for 16 blocks,
# mSBC (HFP wide-band, syncword 0xAD) uses the same code for 15 blocks. The
# decoder distinguishes by syncword, so SBCHeader.from_bytes must be told which
# wire-format it's reading.
_BLOCKS_INV = {0b00: 4, 0b01: 8, 0b10: 12, 0b11: 16}
_CHANNEL_MODES = {
    "mono": 0b00, "dual": 0b01, "stereo": 0b10, "joint_stereo": 0b11,
}
_CHANNEL_MODES_INV = {v: k for k, v in _CHANNEL_MODES.items()}
_ALLOCATIONS = {"loudness": 0b0, "snr": 0b1}
_ALLOCATIONS_INV = {v: k for k, v in _ALLOCATIONS.items()}
_SUBBANDS = {4: 0b0, 8: 0b1}
_SUBBANDS_INV = {v: k for k, v in _SUBBANDS.items()}

_SYNCWORD = 0x9C
_MSBC_SYNCWORD = 0xAD


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

    def to_bytes(self, *, payload_for_crc: bytes = b"", syncword: int = _SYNCWORD) -> bytes:
        """Encode the 4-byte header. `payload_for_crc` is the CRC-covered region after
        bytes 1-2 (scale factors + join bits) when available. `syncword` defaults
        to 0x9C (SBC); mSBC callers pass 0xAD."""
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
        return bytes([syncword, b1, b2, crc])

    @classmethod
    def from_bytes(cls, data: bytes) -> "SBCHeader":
        if len(data) < 4:
            raise ValueError("data too short for SBC header (need ≥ 4 bytes)")
        if data[0] not in (_SYNCWORD, _MSBC_SYNCWORD):
            raise ValueError(
                f"bad syncword 0x{data[0]:02X}, expected 0x9C (SBC) or 0xAD (mSBC)"
            )
        b1 = data[1]
        bitpool = data[2]
        sr = _SAMPLE_RATES_INV[(b1 >> 6) & 0b11]
        blocks = _BLOCKS_INV[(b1 >> 4) & 0b11]
        # mSBC overloads code 0b11 to mean 15 blocks (vs SBC's 16). Detect from syncword.
        if data[0] == _MSBC_SYNCWORD and blocks == 16:
            blocks = 15
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


# Loudness offset table per A2DP v1.4 §B.6.3 Table B.8 (rows: sampling-freq index;
# cols: subband). Source: nxp-upstream/libsbc encoder/srce/sbc_enc_bit_alloc_mono.c
# `sbc_enc_as16Offset8` (Apache 2.0 / Broadcom).
_LOUDNESS_OFFSET_8 = (
    (-2, 0, 0, 0, 0, 0, 0, 1),    # 16 kHz
    (-3, 0, 0, 0, 0, 0, 1, 2),    # 32 kHz
    (-4, 0, 0, 0, 0, 0, 1, 2),    # 44.1 kHz
    (-4, 0, 0, 0, 0, 0, 1, 2),    # 48 kHz
)
_LOUDNESS_OFFSET_4 = (
    (-1, 0, 0, 0),
    (-2, 0, 0, 1),
    (-2, 0, 0, 1),
    (-2, 0, 0, 1),
)


def _compute_scale_factors(
    blocks: list[list[int]], channels: int,
) -> list[list[int]]:
    """Per A2DP §B.6.1: scale_factor[ch][sb] = max bits needed to represent the
    largest absolute sample value across all blocks for that (channel, subband).

    Returns list[ch][sb] of int (0..15).

    Input `blocks` shape: list[blocks][subband_idx], where each row has length
    subbands*channels, interleaved as (sb0_ch0, sb0_ch1, sb1_ch0, sb1_ch1, ...)
    for stereo, or just (sb0, sb1, ...) for mono.
    """
    if channels < 1 or channels > 2:
        raise ValueError(f"channels must be 1 or 2, got {channels}")
    if not blocks:
        return [[0] * 0 for _ in range(channels)]
    subbands = len(blocks[0]) // channels
    result: list[list[int]] = []
    for ch in range(channels):
        sf_per_sb: list[int] = []
        for sb in range(subbands):
            max_abs = 0
            for blk in blocks:
                v = abs(blk[sb * channels + ch])
                if v > max_abs:
                    max_abs = v
            # scale_factor = bit_length(max_abs); 0 for max_abs=0.
            sf_per_sb.append(max_abs.bit_length())
        result.append(sf_per_sb)
    return result


def _bit_allocation_loudness(
    scale_factors: list[list[int]],
    *,
    bitpool: int,
    sample_rate: int,
    subbands: int,
    channel_mode: str = "mono",
) -> list[list[int]]:
    """A2DP v1.4 §B.6.3 loudness bit-allocation algorithm.

    For mono / dual: each channel gets `bitpool` bits per block, allocated
    independently. For stereo / joint_stereo: both channels share `bitpool`
    total bits per block, allocated jointly. Port of BlueZ sbc/sbc.c
    sbc_calculate_bits_internal (LGPL-2.1+).

    Returns list[ch][sb] of int (0..16): bits per subband.
    """
    if sample_rate not in _SAMPLE_RATES:
        raise ValueError(f"unsupported sample_rate {sample_rate}")
    sf_idx = _SAMPLE_RATES[sample_rate]
    if subbands == 8:
        offsets = _LOUDNESS_OFFSET_8[sf_idx]
    elif subbands == 4:
        offsets = _LOUDNESS_OFFSET_4[sf_idx]
    else:
        raise ValueError(f"subbands must be 4 or 8, got {subbands}")

    channels = len(scale_factors)
    joint = channel_mode in ("stereo", "joint_stereo") and channels == 2

    def compute_bitneed(sf_ch: list[int]) -> list[int]:
        out = [0] * subbands
        for sb in range(subbands):
            if sf_ch[sb] == 0:
                out[sb] = -5
            else:
                loudness = sf_ch[sb] - offsets[sb]
                out[sb] = loudness >> 1 if loudness > 0 else loudness
        return out

    if not joint:
        # Per-channel independent allocation (mono / dual).
        result: list[list[int]] = [[0] * subbands for _ in range(channels)]
        for ch in range(channels):
            bitneed = compute_bitneed(scale_factors[ch])
            result[ch] = _allocate_channel(bitneed, bitpool, subbands)
        return result

    # Joint allocation across both channels (stereo / joint_stereo).
    bitneed = [compute_bitneed(scale_factors[ch]) for ch in range(2)]
    flat_bitneed = bitneed[0] + bitneed[1]   # 2*subbands entries
    max_bitneed = max(0, max(flat_bitneed))
    if max_bitneed == 0:
        return [[0] * subbands, [0] * subbands]

    # Bitslice threshold search across both channels.
    bitslice = max_bitneed + 1
    bit_count = bitpool
    slice_count = 0
    min_bitslice = min(flat_bitneed) - 1
    while bitslice > min_bitslice:
        bitslice -= 1
        bit_count -= slice_count
        slice_count = 0
        for v in flat_bitneed:
            diff = v - bitslice
            if 1 <= diff < 16:
                slice_count += 2 if diff == 1 else 1
        if bit_count - slice_count <= 0:
            break
    if bit_count == 0:
        bit_count -= slice_count
        bitslice -= 1

    # Initial allocation per (ch, sb).
    bits = [[0] * subbands for _ in range(2)]
    for ch in range(2):
        for sb in range(subbands):
            if bitneed[ch][sb] < bitslice + 2:
                bits[ch][sb] = 0
            else:
                diff = bitneed[ch][sb] - bitslice
                bits[ch][sb] = diff if diff < 16 else 16

    # Pass 1 — alternating (sb, ch) order per BlueZ ref.
    ch_idx, sb_idx = 0, 0
    while bit_count > 0:
        if 2 <= bits[ch_idx][sb_idx] < 16:
            bits[ch_idx][sb_idx] += 1
            bit_count -= 1
        elif bitneed[ch_idx][sb_idx] == bitslice + 1 and bit_count > 1:
            bits[ch_idx][sb_idx] = 2
            bit_count -= 2
        if ch_idx == 1:
            ch_idx = 0
            sb_idx += 1
            if sb_idx >= subbands:
                break
        else:
            ch_idx = 1

    # Pass 2 — fill remaining bits, alternating channels.
    ch_idx, sb_idx = 0, 0
    while bit_count > 0:
        if bits[ch_idx][sb_idx] < 16:
            bits[ch_idx][sb_idx] += 1
            bit_count -= 1
        if ch_idx == 1:
            ch_idx = 0
            sb_idx += 1
            if sb_idx >= subbands:
                break
        else:
            ch_idx = 1
    return bits


def _allocate_channel(bitneed: list[int], bitpool: int, subbands: int) -> list[int]:
    """Single-channel bit allocation (mono / dual). Returns bits[sb]."""
    max_bitneed = max(0, max(bitneed))
    if max_bitneed == 0:
        return [0] * subbands
    bitslice = max_bitneed + 1
    bit_count = bitpool
    slice_count = 0
    min_bitslice = min(bitneed) - 1
    while bitslice > min_bitslice:
        bitslice -= 1
        bit_count -= slice_count
        slice_count = 0
        for sb in range(subbands):
            diff = bitneed[sb] - bitslice
            if 1 <= diff < 16:
                slice_count += 2 if diff == 1 else 1
        if bit_count - slice_count <= 0:
            break
    if bit_count == 0:
        bit_count -= slice_count
        bitslice -= 1
    bits = [0] * subbands
    for sb in range(subbands):
        if bitneed[sb] < bitslice + 2:
            bits[sb] = 0
        else:
            diff = bitneed[sb] - bitslice
            bits[sb] = diff if diff < 16 else 16
    sb = 0
    while bit_count > 0 and sb < subbands:
        if 2 <= bits[sb] < 16:
            bits[sb] += 1
            bit_count -= 1
        elif bitneed[sb] == bitslice + 1 and bit_count > 1:
            bits[sb] = 2
            bit_count -= 2
        sb += 1
    sb = 0
    while bit_count > 0 and sb < subbands:
        if bits[sb] < 16:
            bits[sb] += 1
            bit_count -= 1
        sb += 1
    return bits


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


class SBCEncoder:
    """A2DP v1.4 §B SBC encoder. Encodes int16 PCM blocks into SBC frames.

    Constructor pins all codec parameters; each `encode()` call consumes exactly
    `blocks × subbands × channels` int16 samples and produces one SBC frame.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        channel_mode: str,
        blocks: int,
        subbands: int,
        allocation: str,
        bitpool: int,
        syncword: int = _SYNCWORD,
    ) -> None:
        # Channel-mode/channel-count consistency.
        expected_ch = 1 if channel_mode == "mono" else 2
        if channels != expected_ch:
            raise ValueError(
                f"channel_mode={channel_mode!r} implies {expected_ch} channels, "
                f"got channels={channels}"
            )
        # Header construction also validates sample_rate/blocks/subbands/etc.
        self._hdr_template = SBCHeader(
            sample_rate=sample_rate, blocks=blocks, channel_mode=channel_mode,
            allocation=allocation, subbands=subbands, bitpool=bitpool,
        )
        self._syncword = syncword
        self.sample_rate = sample_rate
        self.channels = channels
        self.channel_mode = channel_mode
        self.blocks = blocks
        self.subbands = subbands
        self.allocation = allocation
        self.bitpool = bitpool
        self._samples_per_frame = blocks * subbands * channels

    @property
    def frame_size(self) -> int:
        return self._hdr_template.frame_length()

    def encode(self, pcm_bytes: bytes) -> bytes:
        """Encode one frame worth of int16 LE PCM samples.

        Returns: a complete SBC frame (4-byte header + scale factors + samples).
        """
        expected = 2 * self._samples_per_frame
        if len(pcm_bytes) != expected:
            raise ValueError(
                f"pcm_bytes length {len(pcm_bytes)} doesn't match expected {expected} "
                f"(blocks={self.blocks} × subbands={self.subbands} × "
                f"channels={self.channels} × 2 bytes)"
            )
        # Plan A.1 supports 8-subband only at encode-time (4-subband analysis
        # filter would be a future extension). Reject 4-subband cleanly.
        if self.subbands != 8:
            raise NotImplementedError(
                f"SBCEncoder: subbands={self.subbands} not supported in Plan A.1 "
                f"(only subbands=8)"
            )
        if self.allocation != "loudness":
            raise NotImplementedError(
                f"SBCEncoder: allocation={self.allocation!r} not supported in Plan A.1 "
                f"(only 'loudness')"
            )

        # 1. De-interleave PCM into per-channel streams.
        pcm = list(struct.unpack(f"<{self._samples_per_frame}h", pcm_bytes))
        if self.channels == 2:
            pcm_l = pcm[0::2]
            pcm_r = pcm[1::2]
            blocks_l = _analysis_filter_8(pcm_l)
            blocks_r = _analysis_filter_8(pcm_r)
            # Re-interleave per-block: row[sb*2 + ch]
            samples_blocks = [
                [v for pair in zip(blocks_l[b], blocks_r[b]) for v in pair]
                for b in range(self.blocks)
            ]
        else:
            samples_blocks = _analysis_filter_8(pcm)

        # 2. Scale factors per channel/subband.
        scale_factors = _compute_scale_factors(samples_blocks, channels=self.channels)

        # 3. Loudness bit allocation.
        bits = _bit_allocation_loudness(
            scale_factors,
            bitpool=self.bitpool,
            sample_rate=self.sample_rate,
            subbands=self.subbands,
            channel_mode=self.channel_mode,
        )

        # 4. Build post-header bitstream (scale factors + join bits + quantized samples).
        bw = BitWriter()
        # 4a. Scale factors: 4 bits each, channel-major.
        for ch in range(self.channels):
            for sb in range(self.subbands):
                bw.write(scale_factors[ch][sb] & 0xF, 4)
        # 4b. Join bits — Plan A.1 doesn't apply joint coding (zeroes pad the
        # joint-stereo flag bits). The slot is still reserved per A2DP §B.6.4.
        if self.channel_mode == "joint_stereo":
            bw.write(0, self.subbands)
        # 4c. Quantized samples — block-major, then channel, then subband.
        for blk in range(self.blocks):
            for ch in range(self.channels):
                for sb in range(self.subbands):
                    nbits = bits[ch][sb]
                    if nbits == 0:
                        continue
                    sample = samples_blocks[blk][sb * self.channels + ch]
                    sf = scale_factors[ch][sb]
                    if sf == 0:
                        q = 0
                    else:
                        # Inverse of the decoder's dequant (matched pair):
                        #   dequant = 2^sf * ((2q + 1) / (2^nbits - 1) - 1)
                        # Maps signed sample in [-2^sf, 2^sf) → q in [0, levels],
                        # rounded to nearest.
                        levels = (1 << nbits) - 1
                        two_sf = 1 << sf
                        q = ((sample + two_sf) * levels + two_sf) // (two_sf << 1)
                        if q < 0:
                            q = 0
                        elif q > levels:
                            q = levels
                    bw.write(q, nbits)
        post_header = bytes(bw.finish())

        # 4d. Pad post-header to exactly (frame_length - 4) bytes.
        # The bit-allocation algorithm may consume fewer than `bitpool` bits per
        # block when scale factors are low; SBC frames are fixed-length per the
        # header config, so the remaining bytes are zero-padded.
        expected_post_len = self._hdr_template.frame_length() - 4
        if len(post_header) < expected_post_len:
            post_header = post_header + bytes(expected_post_len - len(post_header))
        elif len(post_header) > expected_post_len:
            # Should not happen; would indicate a bit-allocation overrun.
            raise RuntimeError(
                f"SBC encode: post-header overflow ({len(post_header)} > {expected_post_len})"
            )

        # 5. Header with CRC over post-header bits up to end of join bits.
        # For simplicity in Plan A.1, CRC covers scale factors + join bits.
        # Bytes covered = scale_factor_bytes + join_bytes (joint stereo only).
        if self.channel_mode == "joint_stereo":
            join_bits = self.subbands
        else:
            join_bits = 0
        nb = self.subbands * self.channels
        scale_factor_bytes = math.ceil(nb / 2)
        crc_payload_bytes = scale_factor_bytes + math.ceil(join_bits / 8)
        crc_payload = post_header[:crc_payload_bytes]
        header = self._hdr_template.to_bytes(
            payload_for_crc=crc_payload, syncword=self._syncword
        )
        return header + post_header


# N[i][k] = cos((2k+1)(i-4)π/16) — synthesis cosine matrix per A2DP v1.4 §B.5
# (transpose of the analysis matrix M).
_SYNTH_N_8 = [
    [math.cos((2 * k + 1) * (i - 4) * math.pi / 16) for k in range(8)]
    for i in range(16)
]


def _synthesis_filter_8(blocks_subbands: list[list[int]], v_state: list[float]) -> list[int]:
    """SBC 8-subband polyphase synthesis filter per A2DP v1.4 §B.5.

    Args:
        blocks_subbands: list[blocks] of list[8] subband samples.
        v_state: 160-element list, MUTATED to track running synthesis state
                 across calls (caller initializes to zeros once per channel).

    Returns:
        Flat list of int PCM samples (8 per block).
    """
    out: list[int] = []
    for s_block in blocks_subbands:
        # 1. Shift V buffer up by 16
        for i in range(159, 15, -1):
            v_state[i] = v_state[i - 16]
        # 2. IDCT: V[0..15] = N · S
        for i in range(16):
            v_state[i] = sum(_SYNTH_N_8[i][k] * s_block[k] for k in range(8))
        # 3. Build U[0..79] from V (A2DP §B.5)
        u = [0.0] * 80
        for j in range(5):
            for i in range(8):
                u[16 * j + i] = v_state[32 * j + i]
                u[16 * j + i + 8] = v_state[32 * j + i + 24]
        # 4. Window with proto C[] coefficients × per-phase sign alternation,
        # then 10-tap overlap-add. The (-1)**k sign pattern across the 10 polyphase
        # phases is the standard pseudo-QMF synthesis pattern that cancels
        # aliasing between adjacent blocks. Final scale factor (×8) matches the
        # filter bank gain so output magnitude tracks the original PCM.
        for i in range(8):
            s = sum(
                ((-1) ** k) * _PROTO_FILTER_8[i + 8 * k] * u[i + 8 * k]
                for k in range(10)
            )
            # Negate to align polarity with the analysis filter (the pseudo-QMF
            # design intrinsically sign-flips the reconstruction; cancel it).
            out.append(int(round(-s * 8.0)))
    return out


class SBCDecoder:
    """A2DP v1.4 §B SBC decoder. Pure DSP, no Bluetooth deps.

    Decoder is stateful: synthesis filter V-buffers persist across `decode()`
    calls (one per channel index), so streamed frames reconstruct smoothly.
    Construct one decoder per stream.
    """

    def __init__(self) -> None:
        self._v_state: dict[int, list[float]] = {}

    def _get_v_state(self, ch: int) -> list[float]:
        v = self._v_state.get(ch)
        if v is None:
            v = [0.0] * 160
            self._v_state[ch] = v
        return v

    def decode(self, data: bytes) -> tuple[bytes, int]:
        """Decode one or more complete SBC frames from `data`.

        Reads frames starting at byte 0 until the remaining bytes are smaller
        than the next frame; leftover bytes are reported via `consumed`.

        Args:
            data: bytes starting with the SBC frame syncword.

        Returns:
            (pcm_le16, consumed_bytes) — interleaved int16 LE PCM (all decoded
            frames concatenated) and the total bytes consumed.
        """
        if len(data) < 4 or data[0] not in (_SYNCWORD, _MSBC_SYNCWORD):
            raise ValueError(
                f"SBC syncword 0x9C / 0xAD not found at byte 0 (got {data[:1].hex()})"
            )

        pcm_chunks: list[bytes] = []
        offset = 0
        while offset + 4 <= len(data) and data[offset] in (_SYNCWORD, _MSBC_SYNCWORD):
            header = SBCHeader.from_bytes(data[offset:offset + 4])
            frame_size = header.frame_length()
            if offset + frame_size > len(data):
                break
            chunk = self._decode_one(data[offset:offset + frame_size], header)
            pcm_chunks.append(chunk)
            offset += frame_size

        if offset == 0:
            # Couldn't decode anything (e.g., truncated single frame).
            raise ValueError("no complete SBC frame found in input")

        return b"".join(pcm_chunks), offset

    def _decode_one(self, frame: bytes, header: SBCHeader) -> bytes:
        post_header = frame[4:]
        if header.subbands != 8:
            raise NotImplementedError(
                f"SBCDecoder: subbands={header.subbands} not supported in Plan A.1 "
                f"(only subbands=8)"
            )

        channels = header.channels
        subbands = header.subbands
        blocks = header.blocks
        br = BitReader(post_header)

        # Read scale factors (4 bits each, channel-major).
        scale_factors: list[list[int]] = [[0] * subbands for _ in range(channels)]
        for ch in range(channels):
            for sb in range(subbands):
                scale_factors[ch][sb] = br.read(4)

        # Skip join bits (we don't apply joint coding in Plan A.1).
        if header.channel_mode == "joint_stereo":
            br.read(subbands)

        # Bit allocation from scale factors (identical to encoder).
        bits = _bit_allocation_loudness(
            scale_factors,
            bitpool=header.bitpool,
            sample_rate=header.sample_rate,
            subbands=subbands,
            channel_mode=header.channel_mode,
        )

        # Read quantized samples block-major, dequantize, accumulate per channel.
        per_channel_blocks: list[list[list[int]]] = [
            [[0] * subbands for _ in range(blocks)] for _ in range(channels)
        ]
        for blk in range(blocks):
            for ch in range(channels):
                for sb in range(subbands):
                    nbits = bits[ch][sb]
                    sf = scale_factors[ch][sb]
                    if nbits == 0 or sf == 0:
                        per_channel_blocks[ch][blk][sb] = 0
                    else:
                        q = br.read(nbits)
                        levels = (1 << nbits) - 1
                        # dequant = ((2q + 1) << sf) // levels - (1 << sf)
                        sample = ((2 * q + 1) << sf) // levels - (1 << sf)
                        per_channel_blocks[ch][blk][sb] = sample

        # Synthesis filter per channel.
        per_channel_pcm: list[list[int]] = []
        for ch in range(channels):
            v = self._get_v_state(ch)
            pcm_ch = _synthesis_filter_8(per_channel_blocks[ch], v)
            # Clamp to int16 range to handle filter ringing on transients.
            pcm_ch = [max(-32768, min(32767, s)) for s in pcm_ch]
            per_channel_pcm.append(pcm_ch)

        # Interleave channels.
        if channels == 1:
            interleaved = per_channel_pcm[0]
        else:
            interleaved = [
                v for pair in zip(per_channel_pcm[0], per_channel_pcm[1]) for v in pair
            ]
        return struct.pack(f"<{len(interleaved)}h", *interleaved)


# ---------------------------------------------------------------------
# Backend selection.
#
# The pure-Python SBCEncoder/Decoder above is correct in structure but uses a
# simplified filter bank that lacks the SBC pseudo-QMF perfect-reconstruction
# design (see Plan A.1 Task 7 deferral). Audio reconstruction PSNR is ~20 dB
# vs ~80 dB for a reference impl. When libsbc.so.1 (BlueZ SBC, LGPL-2.1+) is
# available on the system, we transparently swap the classes here so callers
# get production-grade SBC byte-for-byte.
#
# Pure-Python classes remain accessible as _PurePythonSBCEncoder /
# _PurePythonSBCDecoder for tests that target the codec internals directly,
# and for portability when libsbc isn't installed.
# ---------------------------------------------------------------------

_PurePythonSBCEncoder = SBCEncoder
_PurePythonSBCDecoder = SBCDecoder

try:  # pragma: no cover — branch tested explicitly in test_libsbc_backend
    from pybluehost.audio.codec._sbc_libsbc import (
        LibsbcSBCEncoder as _LibsbcSBCEncoder,
        LibsbcSBCDecoder as _LibsbcSBCDecoder,
        is_available as _libsbc_available,
    )
    if _libsbc_available():
        SBCEncoder = _LibsbcSBCEncoder  # type: ignore[misc,assignment]
        SBCDecoder = _LibsbcSBCDecoder  # type: ignore[misc,assignment]
        _SBC_BACKEND = "libsbc"
    else:
        _SBC_BACKEND = "pure-python"
except ImportError:  # pragma: no cover
    _SBC_BACKEND = "pure-python"


def sbc_backend() -> str:
    """Returns the active SBC backend: 'libsbc' or 'pure-python'."""
    return _SBC_BACKEND
