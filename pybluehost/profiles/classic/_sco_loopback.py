"""WAV <-> SCO data path workers — Plan A.4 file-based loopback.

`WavToScoSender` reads a WAV file, encodes each frame with CVSD or mSBC, and
sends as HCI SCO data packets. `ScoToWavReceiver` registers an `on_data`
callback on the SCOLink, decodes inbound packets, and appends to a WAV file.

Frame sizes (Plan A.4):
- CVSD : 30 bytes per packet = 240 PCM samples at 8 kHz  (30 ms)
- mSBC : 57 bytes per SBC frame = 120 PCM samples at 16 kHz (7.5 ms).
         The sender packs TWO SBC frames per SCO packet to yield 240 PCM
         samples (15 ms) per packet; the receiver decodes both frames.
"""
from __future__ import annotations

import asyncio
import wave

from pybluehost.audio.codec import (
    CVSDDecoder, CVSDEncoder, MSBCDecoder, MSBCEncoder,
)
from pybluehost.hci.sco import SCOLink


# Per-codec configuration.
# samples_per_frame: number of PCM int16 samples consumed/produced per packet.
_CODEC_PROFILE: dict[str, dict] = {
    "CVSD": {"sample_rate": 8000,  "samples_per_frame": 240},
    # mSBC encodes 120 samples per SBC frame; we send 2 frames per SCO packet.
    "mSBC": {"sample_rate": 16000, "samples_per_frame": 120},
}

# mSBC SBC frame size in bytes (blocks=15, subbands=8, bitpool=26, mono).
_MSBC_FRAME_BYTES = 57


class WavToScoSender:
    """Reads a WAV file in fixed-size PCM frames, encodes, and emits SCO packets.

    For mSBC two SBC frames (120 samples each) are packed into one SCO packet,
    giving 240 total PCM samples (15 ms) per HCI SCO Data PDU.
    """

    def __init__(self, *, wav_path: str, sco_link: SCOLink) -> None:
        if sco_link.codec not in _CODEC_PROFILE:
            raise ValueError(f"unsupported codec {sco_link.codec!r}")
        prof = _CODEC_PROFILE[sco_link.codec]

        self._wav = wave.open(wav_path, "rb")
        if self._wav.getnchannels() != 1:
            self._wav.close()
            raise ValueError("WAV must be mono")
        if self._wav.getframerate() != prof["sample_rate"]:
            self._wav.close()
            raise ValueError(
                f"WAV sample rate {self._wav.getframerate()} does not match "
                f"expected sample rate {prof['sample_rate']} for codec "
                f"{sco_link.codec!r}"
            )

        self._sco_link = sco_link
        self._samples_per_frame = prof["samples_per_frame"]
        self._codec = sco_link.codec

        if sco_link.codec == "CVSD":
            self._encoder: CVSDEncoder | MSBCEncoder = CVSDEncoder()
        else:
            self._encoder = MSBCEncoder()

    async def run(self) -> int:
        """Stream all complete frames; return total encoded bytes sent over SCO.

        For mSBC: reads two consecutive 120-sample chunks, encodes each into a
        57-byte SBC frame, concatenates them, and sends the 114-byte payload as
        one SCO packet.
        """
        total = 0
        bytes_per_read = self._samples_per_frame * 2  # int16 LE

        if self._codec == "mSBC":
            # Pack two mSBC frames per SCO packet.
            while True:
                chunk_a = self._wav.readframes(self._samples_per_frame)
                if len(chunk_a) < bytes_per_read:
                    break
                chunk_b = self._wav.readframes(self._samples_per_frame)
                if len(chunk_b) < bytes_per_read:
                    break
                encoded = self._encoder.encode(chunk_a) + self._encoder.encode(chunk_b)
                await self._sco_link.send(encoded)
                total += len(encoded)
                await asyncio.sleep(0)
        else:
            # CVSD: one encode call per packet.
            while True:
                pcm = self._wav.readframes(self._samples_per_frame)
                if len(pcm) < bytes_per_read:
                    break
                encoded = self._encoder.encode(pcm)
                await self._sco_link.send(encoded)
                total += len(encoded)
                await asyncio.sleep(0)

        self._wav.close()
        return total


class ScoToWavReceiver:
    """Receives HCI SCO payloads via SCOLink callback, decodes, appends to WAV.

    For mSBC the inbound payload contains two 57-byte SBC frames; both are
    decoded and their PCM output written sequentially.
    """

    def __init__(self, *, wav_path: str, sco_link: SCOLink) -> None:
        if sco_link.codec not in _CODEC_PROFILE:
            raise ValueError(f"unsupported codec {sco_link.codec!r}")
        prof = _CODEC_PROFILE[sco_link.codec]

        self._wav = wave.open(wav_path, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(prof["sample_rate"])
        self._codec = sco_link.codec

        if sco_link.codec == "CVSD":
            self._decoder: CVSDDecoder | MSBCDecoder = CVSDDecoder()
        else:
            self._decoder = MSBCDecoder()

        sco_link.set_on_data(self._on_data)

    async def _on_data(self, data: bytes) -> None:
        """Decode inbound SCO payload and write PCM frames to WAV."""
        if self._codec == "mSBC":
            # Two back-to-back 57-byte mSBC frames per packet.
            offset = 0
            while offset + _MSBC_FRAME_BYTES <= len(data):
                frame = data[offset: offset + _MSBC_FRAME_BYTES]
                pcm = self._decoder.decode(frame)
                self._wav.writeframes(pcm)
                offset += _MSBC_FRAME_BYTES
        else:
            pcm = self._decoder.decode(data)
            self._wav.writeframes(pcm)

    def close(self) -> None:
        """Flush and close the output WAV file."""
        try:
            self._wav.close()
        except Exception:
            pass
