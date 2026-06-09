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
