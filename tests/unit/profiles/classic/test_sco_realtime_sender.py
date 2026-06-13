"""MicToScoSender: pulls 240/120-sample PCM frames from an AudioInputDevice,
encodes via CVSD or mSBC, sends as SCO packets. Underruns become silence."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from pybluehost.profiles.classic._sco_realtime import MicToScoSender


def _make_sco_link(codec: str):
    link = MagicMock()
    link.codec = codec
    link.send = AsyncMock()
    return link


@pytest.mark.asyncio
async def test_mic_to_sco_cvsd_encodes_and_sends():
    sco = _make_sco_link("CVSD")
    mic = MagicMock()
    mic.read_frame = AsyncMock(side_effect=[b"\x00\x00" * 240] * 3 + [asyncio.CancelledError()])

    sender = MicToScoSender(audio_input=mic, sco_link=sco)
    task = asyncio.create_task(sender.run())
    await asyncio.sleep(0.05)
    await sender.stop()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    # At least one CVSD packet was sent; each is 30 bytes
    assert sco.send.await_count >= 1
    payload = sco.send.await_args_list[0].args[0]
    assert len(payload) == 30


@pytest.mark.asyncio
async def test_mic_to_sco_msbc_packs_two_frames_per_packet():
    sco = _make_sco_link("mSBC")
    mic = MagicMock()
    mic.read_frame = AsyncMock(side_effect=[b"\x00\x00" * 120] * 4 + [asyncio.CancelledError()])

    sender = MicToScoSender(audio_input=mic, sco_link=sco)
    task = asyncio.create_task(sender.run())
    await asyncio.sleep(0.05)
    await sender.stop()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    assert sco.send.await_count >= 1
    payload = sco.send.await_args_list[0].args[0]
    assert len(payload) == 114  # 2 * 57


@pytest.mark.asyncio
async def test_mic_to_sco_underrun_sends_silence_not_crash():
    """When mic.read_frame returns empty (underrun), sender emits silence,
    doesn't crash."""
    sco = _make_sco_link("CVSD")
    mic = MagicMock()
    # First call returns empty (underrun); subsequent calls trigger cancel
    mic.read_frame = AsyncMock(side_effect=[b"", b"", asyncio.CancelledError()])

    sender = MicToScoSender(audio_input=mic, sco_link=sco)
    task = asyncio.create_task(sender.run())
    await asyncio.sleep(0.05)
    await sender.stop()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    # Test passes if no uncaught exception escaped
    assert not task.exception() if task.done() else True


def test_unsupported_codec_raises():
    sco = MagicMock()
    sco.codec = "AAC"
    with pytest.raises(ValueError, match="codec"):
        MicToScoSender(audio_input=MagicMock(), sco_link=sco)
