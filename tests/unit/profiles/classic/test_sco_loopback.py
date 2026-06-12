"""Tests for WAV <-> SCO loopback workers (Plan A.4 Task 8)."""
import asyncio
import math
import os
import struct
import wave

import pytest

from pybluehost.hci.packets import HCISCOData
from pybluehost.hci.sco import SCOLink
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)


def _make_sine_wav(path: str, *, sample_rate: int, secs: float, freq: float = 400.0) -> int:
    n_samples = int(sample_rate * secs)
    samples = [int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))
               for i in range(n_samples)]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n_samples}h", *samples))
    return n_samples


class _FakeController:
    """Holds outbound SCO data and forwards it back to a target SCOLink.

    SCOLink.send calls controller.send_sco_data(handle, data) with two args,
    so that is the signature we implement here.  We then wrap in HCISCOData
    before forwarding to the sink link's _on_inbound.
    """

    def __init__(self) -> None:
        self.sent: list[HCISCOData] = []
        self._sink: SCOLink | None = None

    def attach_sink(self, sco_link: SCOLink) -> None:
        self._sink = sco_link

    async def send_sco_data(self, handle: int, data: bytes) -> None:
        pkt = HCISCOData(handle=handle, data=data)
        self.sent.append(pkt)
        if self._sink is not None:
            await self._sink._on_inbound(pkt)


@pytest.mark.asyncio
async def test_cvsd_wav_to_sco_to_wav_round_trip(tmp_path):
    src = tmp_path / "src.wav"
    dst = tmp_path / "dst.wav"
    _make_sine_wav(str(src), sample_rate=8000, secs=0.25)

    ctrl = _FakeController()
    sender_link = SCOLink(handle=0x42, codec="CVSD", controller=ctrl)
    receiver_link = SCOLink(handle=0x42, codec="CVSD")
    ctrl.attach_sink(receiver_link)

    receiver = ScoToWavReceiver(wav_path=str(dst), sco_link=receiver_link)
    sender = WavToScoSender(wav_path=str(src), sco_link=sender_link)

    sent_bytes = await sender.run()
    # Drain any in-flight loopback (FakeController is synchronous).
    await asyncio.sleep(0)
    receiver.close()

    assert sent_bytes > 0
    assert os.path.exists(dst)
    with wave.open(str(dst), "rb") as r:
        assert r.getnchannels() == 1
        assert r.getframerate() == 8000


@pytest.mark.asyncio
async def test_msbc_wav_to_sco_to_wav_round_trip(tmp_path):
    src = tmp_path / "src.wav"
    dst = tmp_path / "dst.wav"
    _make_sine_wav(str(src), sample_rate=16000, secs=0.25)

    ctrl = _FakeController()
    sender_link = SCOLink(handle=0x99, codec="mSBC", controller=ctrl)
    receiver_link = SCOLink(handle=0x99, codec="mSBC")
    ctrl.attach_sink(receiver_link)

    receiver = ScoToWavReceiver(wav_path=str(dst), sco_link=receiver_link)
    sender = WavToScoSender(wav_path=str(src), sco_link=sender_link)

    sent_bytes = await sender.run()
    await asyncio.sleep(0)
    receiver.close()

    assert sent_bytes > 0
    with wave.open(str(dst), "rb") as r:
        assert r.getframerate() == 16000


@pytest.mark.asyncio
async def test_wav_to_sco_rejects_wrong_sample_rate(tmp_path):
    src = tmp_path / "src.wav"
    _make_sine_wav(str(src), sample_rate=44100, secs=0.1)
    ctrl = _FakeController()
    sender_link = SCOLink(handle=0x1, codec="CVSD", controller=ctrl)
    with pytest.raises(ValueError, match="sample rate"):
        WavToScoSender(wav_path=str(src), sco_link=sender_link)
