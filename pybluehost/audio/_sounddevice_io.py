"""Lazy `sounddevice` wrapper.

CLIs check `is_available()` and fall back to WAV file I/O when False.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Optional


class SoundDeviceUnavailable(RuntimeError):
    """Raised when an audio operation is attempted but sounddevice isn't installed."""


_sounddevice = None
_sounddevice_import_attempted = False


def _try_import() -> bool:
    global _sounddevice, _sounddevice_import_attempted
    if _sounddevice_import_attempted:
        return _sounddevice is not None
    _sounddevice_import_attempted = True
    try:
        import sounddevice as _sd
        _sounddevice = _sd
        return True
    except Exception:
        _sounddevice = None
        return False


def is_available() -> bool:
    """True if `sounddevice` can be imported AND its PortAudio backend is present."""
    return _try_import()


def list_devices() -> list[dict]:
    if not is_available():
        return []
    assert _sounddevice is not None
    out: list[dict] = []
    for i, dev in enumerate(_sounddevice.query_devices()):
        out.append({
            "index": i,
            "name": dev.get("name", "<unknown>"),
            "channels_in": dev.get("max_input_channels", 0),
            "channels_out": dev.get("max_output_channels", 0),
            "samplerate": dev.get("default_samplerate", 0.0),
        })
    return out


class AudioInputDevice:
    """Async wrapper around sounddevice.InputStream."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int = 1,
        device: Optional[int] = None,
        buffer_frames: int = 480,
    ) -> None:
        if not is_available():
            raise SoundDeviceUnavailable(
                "sounddevice not installed (pip install 'pybluehost[audio]')"
            )
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.buffer_frames = buffer_frames
        self._stream = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status) -> None:
        with self._lock:
            if self._loop is None:
                return
            data = bytes(indata)
            self._loop.call_soon_threadsafe(self._queue.put_nowait, data)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        assert _sounddevice is not None
        self._stream = _sounddevice.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            device=self.device,
            blocksize=self.buffer_frames,
            callback=self._callback,
        )
        self._stream.start()

    async def read_frame(self, n_samples: int) -> bytes:
        target = n_samples * self.channels * 2
        buf = bytearray()
        while len(buf) < target:
            chunk = await self._queue.get()
            buf.extend(chunk)
        return bytes(buf[:target])

    async def stop(self) -> None:
        with self._lock:
            self._loop = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class AudioOutputDevice:
    """Async wrapper around sounddevice.OutputStream."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int = 1,
        device: Optional[int] = None,
        buffer_frames: int = 480,
    ) -> None:
        if not is_available():
            raise SoundDeviceUnavailable(
                "sounddevice not installed (pip install 'pybluehost[audio]')"
            )
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.buffer_frames = buffer_frames
        self._stream = None

    async def start(self) -> None:
        assert _sounddevice is not None
        self._stream = _sounddevice.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            device=self.device,
            blocksize=self.buffer_frames,
        )
        self._stream.start()

    async def write_frame(self, pcm: bytes) -> None:
        if self._stream is None:
            raise RuntimeError("stream not started")
        import numpy as np
        arr = np.frombuffer(pcm, dtype=np.int16).reshape(-1, self.channels)
        self._stream.write(arr)

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
