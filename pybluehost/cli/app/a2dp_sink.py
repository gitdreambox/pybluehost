"""'app a2dp-sink' — receive A2DP audio, write WAV or play via sounddevice."""
from __future__ import annotations

import argparse
import asyncio
import logging
import wave

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.gap_common import ClassOfDevice
from pybluehost.profiles.classic import A2DPSink
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)
_SERVICE_NAME = "PyBlueHost A2DP Sink"
_AUDIO_HEADPHONES_COD = ClassOfDevice(
    major_device_class=0x04,
    minor_device_class=0x06,
    service_class=0x120,
)


def register_a2dp_sink_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "a2dp-sink",
        help="Listen for incoming A2DP audio; write WAV or play via sounddevice",
    )
    add_common_arguments(p)
    p.add_argument(
        "--output", required=True,
        help="WAV file path, or the literal 'device' for sounddevice output",
    )
    p.add_argument(
        "--device-index", type=int, default=None,
        help="sounddevice output device index (only with --output=device)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _a2dp_sink_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _a2dp_sink_main(stack: Stack, stop: asyncio.Event, args) -> None:
    if args.output == "device":
        await _sink_to_device(stack, args.device_index, stop)
    else:
        await _sink_to_wav(stack, args.output, stop)


async def _sink_to_wav(stack: Stack, wav_path: str, stop: asyncio.Event) -> None:
    w = wave.open(wav_path, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)

    async def on_pcm(pcm: bytes) -> None:
        w.writeframes(pcm)

    sink = A2DPSink(stack=stack, on_pcm=on_pcm)
    sink.register()
    discoverability = getattr(getattr(stack, "gap", None), "classic_discoverability", None)
    if discoverability is not None:
        await discoverability.set_device_name(_SERVICE_NAME)
        await discoverability.set_class_of_device(_AUDIO_HEADPHONES_COD)
        await discoverability.set_discoverable(True)
        await discoverability.set_connectable(True)
    logger.info("A2DP sink registered; writing to %s. Ctrl+C to stop.", wav_path)
    try:
        await stop.wait()
    finally:
        if discoverability is not None:
            await discoverability.set_discoverable(False)
            await discoverability.set_connectable(False)
        w.close()
        logger.info("Wrote %s", wav_path)


async def _sink_to_device(stack: Stack, device_index, stop: asyncio.Event) -> None:
    from pybluehost.audio._sounddevice_io import (
        AudioOutputDevice, SoundDeviceUnavailable, is_available,
    )
    if not is_available():
        raise SoundDeviceUnavailable(
            "Install 'pybluehost[audio]' to use live device output"
        )
    dev = AudioOutputDevice(
        sample_rate=44100, channels=2, device=device_index, buffer_frames=256,
    )
    await dev.start()

    async def on_pcm(pcm: bytes) -> None:
        await dev.write_frame(pcm)

    sink = A2DPSink(stack=stack, on_pcm=on_pcm)
    sink.register()
    discoverability = getattr(getattr(stack, "gap", None), "classic_discoverability", None)
    if discoverability is not None:
        await discoverability.set_device_name(_SERVICE_NAME)
        await discoverability.set_class_of_device(_AUDIO_HEADPHONES_COD)
        await discoverability.set_discoverable(True)
        await discoverability.set_connectable(True)
    logger.info("A2DP sink playing through audio device. Ctrl+C to stop.")
    try:
        await stop.wait()
    finally:
        if discoverability is not None:
            await discoverability.set_discoverable(False)
            await discoverability.set_connectable(False)
        await dev.stop()
