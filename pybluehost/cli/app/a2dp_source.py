"""'app a2dp-source' — push WAV or live mic into an A2DP peer."""
from __future__ import annotations

import argparse
import asyncio
import logging
import wave

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.address import BDAddress
from pybluehost.profiles.classic import A2DPSource
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


_A2DP_BYTES_PER_FRAME = 2 * 16 * 8 * 2   # 512 bytes


def register_a2dp_source_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "a2dp-source",
        help="Push a WAV file or live audio device into an A2DP peer",
    )
    add_common_arguments(p)
    p.add_argument("--target", required=True, help="Peer BD_ADDR (AA:BB:CC:DD:EE:FF)")
    p.add_argument(
        "--play", required=True,
        help="WAV file path, or the literal 'device' for sounddevice input",
    )
    p.add_argument(
        "--device-index", type=int, default=None,
        help="sounddevice input device index (only with --play=device)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _a2dp_source_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _a2dp_source_main(stack: Stack, stop: asyncio.Event, args) -> None:
    target = BDAddress.from_string(args.target)
    src = A2DPSource(stack=stack)
    src.register()

    handle = await stack.connect_classic(target, timeout=10.0)
    await stack.authenticate_classic(handle, timeout=10.0)
    session = await src.connect(handle=handle)
    await session.negotiate_codec()
    await session.start()

    try:
        if args.play == "device":
            await _stream_from_device(session, args.device_index, stop)
        else:
            await _stream_from_wav(session, args.play, stop)
    finally:
        await session.close()


async def _stream_from_wav(session, wav_path: str, stop: asyncio.Event) -> None:
    with wave.open(wav_path, "rb") as w:
        if w.getnchannels() != 2 or w.getframerate() != 44100 or w.getsampwidth() != 2:
            raise ValueError(
                f"A2DP source requires 44.1 kHz / 16-bit / stereo WAV; "
                f"got {w.getframerate()} Hz / {w.getsampwidth()*8} bit / {w.getnchannels()} ch"
            )
        n_samples = 256
        while not stop.is_set():
            pcm = w.readframes(n_samples)
            if len(pcm) < _A2DP_BYTES_PER_FRAME:
                break
            await session.send_pcm(pcm)


async def _stream_from_device(session, device_index, stop: asyncio.Event) -> None:
    from pybluehost.audio._sounddevice_io import (
        AudioInputDevice, SoundDeviceUnavailable, is_available,
    )
    if not is_available():
        raise SoundDeviceUnavailable(
            "Install 'pybluehost[audio]' to use live device input"
        )
    dev = AudioInputDevice(
        sample_rate=44100, channels=2, device=device_index, buffer_frames=256,
    )
    await dev.start()
    try:
        while not stop.is_set():
            pcm = await dev.read_frame(256)
            await session.send_pcm(pcm)
    finally:
        await dev.stop()
