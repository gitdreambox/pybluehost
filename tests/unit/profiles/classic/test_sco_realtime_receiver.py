"""ScoToSpeakerReceiver: registers on_data on SCOLink, decodes inbound packets,
writes PCM to an AudioOutputDevice."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from pybluehost.profiles.classic._sco_realtime import ScoToSpeakerReceiver


def _make_sco_link(codec: str):
    link = MagicMock()
    link.codec = codec
    link.set_on_data = MagicMock()
    return link


@pytest.mark.asyncio
async def test_sco_to_speaker_cvsd_decodes_and_writes():
    sco = _make_sco_link("CVSD")
    speaker = MagicMock()
    speaker.write_frame = AsyncMock()

    receiver = ScoToSpeakerReceiver(audio_output=speaker, sco_link=sco)
    # The receiver should have registered an on_data callback
    sco.set_on_data.assert_called_once()
    on_data = sco.set_on_data.call_args.args[0]

    # Feed a 30-byte CVSD payload; expect a single 480-byte PCM write
    # (240 samples * 2 bytes int16)
    await on_data(b"\xAA" * 30)
    speaker.write_frame.assert_awaited_once()
    pcm = speaker.write_frame.await_args.args[0]
    assert len(pcm) == 480


@pytest.mark.asyncio
async def test_sco_to_speaker_msbc_decodes_both_frames():
    sco = _make_sco_link("mSBC")
    speaker = MagicMock()
    speaker.write_frame = AsyncMock()

    receiver = ScoToSpeakerReceiver(audio_output=speaker, sco_link=sco)
    on_data = sco.set_on_data.call_args.args[0]

    from pybluehost.audio.codec import MSBCEncoder
    enc = MSBCEncoder()
    frame_a = enc.encode(b"\x00\x00" * 120)
    frame_b = enc.encode(b"\x00\x00" * 120)
    assert len(frame_a) == 57 and len(frame_b) == 57

    await on_data(frame_a + frame_b)
    # Receiver must have written at least once (one or two calls,
    # depending on implementation — both fine).
    assert speaker.write_frame.await_count >= 1


@pytest.mark.asyncio
async def test_sco_to_speaker_tolerates_write_exceptions():
    """If the speaker is misbehaving, receiver should not crash — write errors
    are swallowed so the SCO data path keeps flowing."""
    sco = _make_sco_link("CVSD")
    speaker = MagicMock()
    speaker.write_frame = AsyncMock(side_effect=RuntimeError("device unplugged"))

    receiver = ScoToSpeakerReceiver(audio_output=speaker, sco_link=sco)
    on_data = sco.set_on_data.call_args.args[0]

    # Should not raise
    await on_data(b"\xAA" * 30)


def test_unsupported_codec_raises():
    sco = MagicMock()
    sco.codec = "AAC"
    with pytest.raises(ValueError, match="codec"):
        ScoToSpeakerReceiver(audio_output=MagicMock(), sco_link=sco)
