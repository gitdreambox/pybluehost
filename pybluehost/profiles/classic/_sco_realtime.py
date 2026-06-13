"""Real-time SCO <-> OS audio workers -- Plan B.2 live mic/speaker path.

Mirrors the WAV-file-based workers in `_sco_loopback.py`:
- `MicToScoSender` pulls PCM from an AudioInputDevice, encodes, sends as SCO.
- (`ScoToSpeakerReceiver` is added in Plan B.2 Task 2.)
"""
from __future__ import annotations

import asyncio

from pybluehost.audio.codec import (
    CVSDDecoder, CVSDEncoder, MSBCDecoder, MSBCEncoder,
)
from pybluehost.hci.sco import SCOLink


_CODEC_PROFILE: dict[str, dict] = {
    "CVSD": {"sample_rate": 8000,  "samples_per_frame": 240},
    "mSBC": {"sample_rate": 16000, "samples_per_frame": 120},
}
_MSBC_FRAME_BYTES = 57


class MicToScoSender:
    """Pulls PCM from an AudioInputDevice, encodes (CVSD or mSBC), sends as SCO.

    Underruns (read_frame returns empty bytes or raises) emit a silence-
    encoded packet so the peer never loses the SCO clock.

    Lifecycle::

      sender = MicToScoSender(audio_input=mic, sco_link=link)
      task = asyncio.create_task(sender.run())
      ...
      await sender.stop()
      await task
    """

    def __init__(self, *, audio_input, sco_link: SCOLink) -> None:
        if sco_link.codec not in _CODEC_PROFILE:
            raise ValueError(f"unsupported codec {sco_link.codec!r}")
        self._audio = audio_input
        self._sco = sco_link
        self._codec = sco_link.codec
        self._samples_per_frame = _CODEC_PROFILE[self._codec]["samples_per_frame"]
        self._encoder: CVSDEncoder | MSBCEncoder = (
            CVSDEncoder() if self._codec == "CVSD" else MSBCEncoder()
        )
        self._stop = asyncio.Event()

    async def _read_or_silence(self) -> bytes:
        """Read one mic frame; on empty/exception return silence PCM bytes."""
        bytes_per_frame = self._samples_per_frame * 2
        silence = b"\x00" * bytes_per_frame
        try:
            pcm = await self._audio.read_frame(self._samples_per_frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            return silence
        if len(pcm) < bytes_per_frame:
            return silence
        return pcm

    async def run(self) -> None:
        """Main loop: read, encode, send until stop() is called."""
        try:
            while not self._stop.is_set():
                if self._codec == "mSBC":
                    pcm_a = await self._read_or_silence()
                    if self._stop.is_set():
                        return
                    pcm_b = await self._read_or_silence()
                    payload = self._encoder.encode(pcm_a) + self._encoder.encode(pcm_b)
                else:
                    pcm = await self._read_or_silence()
                    payload = self._encoder.encode(pcm)
                await self._sco.send(payload)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        """Signal the run loop to exit cleanly."""
        self._stop.set()


class ScoToSpeakerReceiver:
    """Registers an on_data callback on the SCO link, decodes inbound
    payloads (CVSD: one 30-byte frame; mSBC: two 57-byte frames packed),
    and writes PCM to an AudioOutputDevice.

    Write errors are swallowed so a misbehaving speaker can't stall the
    SCO receive path.
    """

    def __init__(self, *, audio_output, sco_link: SCOLink) -> None:
        if sco_link.codec not in _CODEC_PROFILE:
            raise ValueError(f"unsupported codec {sco_link.codec!r}")
        self._audio = audio_output
        self._codec = sco_link.codec
        self._decoder: CVSDDecoder | MSBCDecoder = (
            CVSDDecoder() if self._codec == "CVSD" else MSBCDecoder()
        )
        sco_link.set_on_data(self._on_data)

    async def _on_data(self, data: bytes) -> None:
        if self._codec == "mSBC":
            offset = 0
            while offset + _MSBC_FRAME_BYTES <= len(data):
                frame = data[offset: offset + _MSBC_FRAME_BYTES]
                pcm = self._decoder.decode(frame)
                try:
                    await self._audio.write_frame(pcm)
                except Exception:
                    pass
                offset += _MSBC_FRAME_BYTES
        else:
            pcm = self._decoder.decode(data)
            try:
                await self._audio.write_frame(pcm)
            except Exception:
                pass
