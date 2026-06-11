"""mSBC = SBC configured for HFP wide-band speech (HFP v1.8 §5.7.2).

The mSBC frame syncword is 0xAD (vs SBC's 0x9C); other than that, it's a
strict subset of SBC parameters: 16 kHz / mono / blocks=15 / subbands=8 /
loudness / bitpool=26. Frame is exactly 57 bytes.

blocks=15 is mSBC-only — it overloads the SBC header's 0b11 blocks code
(which standard SBC uses for blocks=16). The decoder distinguishes by
syncword: 0xAD → blocks=15, 0x9C → blocks=16.
"""
from __future__ import annotations

from pybluehost.audio.codec.sbc import SBCDecoder, SBCEncoder


_MSBC_SYNCWORD = 0xAD


class MSBCEncoder:
    """Wide-band speech SBC variant. Frame size 57 bytes (vs 119 for A2DP default)."""

    def __init__(self) -> None:
        self._enc = SBCEncoder(
            sample_rate=16000, channels=1, channel_mode="mono",
            blocks=15, subbands=8, allocation="loudness", bitpool=26,
            syncword=_MSBC_SYNCWORD,
        )

    @property
    def frame_size(self) -> int:
        return self._enc.frame_size

    def encode(self, pcm_bytes: bytes) -> bytes:
        return self._enc.encode(pcm_bytes)


class MSBCDecoder:
    """Inverse of MSBCEncoder. Routes 0xAD-prefixed frames through SBCDecoder."""

    def __init__(self) -> None:
        # libsbc needs sbc_init_msbc (separate init path) for 0xAD frames; the
        # generic SBCDecoder uses sbc_init which can't parse mSBC. Pure-Python
        # SBCDecoder handles both via the same header path.
        try:
            from pybluehost.audio.codec._sbc_libsbc import LibsbcSBCDecoder, is_available
            if is_available():
                self._dec = LibsbcSBCDecoder(msbc=True)
                return
        except ImportError:
            pass
        self._dec = SBCDecoder()

    def decode(self, frame: bytes) -> bytes:
        if len(frame) < 1 or frame[0] != _MSBC_SYNCWORD:
            raise ValueError(
                f"bad mSBC syncword 0x{frame[0] if frame else -1:02X}, expected 0xAD"
            )
        pcm, _ = self._dec.decode(frame)
        return pcm
