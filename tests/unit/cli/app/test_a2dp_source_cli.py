import argparse
import asyncio
import inspect
import math
import struct
import wave

import pytest


def test_register_function_exists():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    assert callable(register_a2dp_source_command)


def test_main_is_async():
    from pybluehost.cli.app.a2dp_source import _a2dp_source_main
    assert inspect.iscoroutinefunction(_a2dp_source_main)


def test_argparse_accepts_required_args():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_source_command(subs)
    args = parser.parse_args([
        "a2dp-source",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--play", "music.wav",
        "--transport", "virtual",
    ])
    assert args.target == "AA:BB:CC:DD:EE:FF"
    assert args.play == "music.wav"


def test_play_device_keyword():
    from pybluehost.cli.app.a2dp_source import register_a2dp_source_command
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_a2dp_source_command(subs)
    args = parser.parse_args([
        "a2dp-source",
        "--target", "AA:BB:CC:DD:EE:FF",
        "--play", "device",
        "--transport", "virtual",
    ])
    assert args.play == "device"


@pytest.mark.asyncio
async def test_stream_from_wav_sends_one_sbc_input_frame_per_chunk(tmp_path):
    from pybluehost.cli.app.a2dp_source import (
        _A2DP_BYTES_PER_FRAME,
        _stream_from_wav,
    )

    wav_path = tmp_path / "music.wav"
    sample_rate = 44100
    stereo_frames = 256
    samples = []
    for i in range(stereo_frames):
        sample = int(6000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        samples.extend([sample, sample])
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    class FakeSession:
        def __init__(self):
            self.chunks = []

        async def send_pcm(self, pcm):
            self.chunks.append(pcm)

    session = FakeSession()
    await _stream_from_wav(session, str(wav_path), asyncio.Event())

    assert [len(chunk) for chunk in session.chunks] == [
        _A2DP_BYTES_PER_FRAME,
        _A2DP_BYTES_PER_FRAME,
    ]
