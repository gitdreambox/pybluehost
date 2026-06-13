"""'app hsp-test' — HSP SCO loopback test (WAV or live mic/speaker, CVSD-only)."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.address import BDAddress
from pybluehost.profiles.classic import HSPAudioGateway, HSPHeadset
from pybluehost.profiles.classic._hsp_constants import HSP_AG_RFCOMM_CHANNEL
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


def register_hsp_test_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "hsp-test",
        help="HSP SCO loopback test — HS pushes audio / AG receives audio",
    )
    add_common_arguments(p)
    p.add_argument("--role", required=True, choices=["hs", "ag"])
    p.add_argument("--target", help="Peer BD_ADDR (required when --role=hs)")

    in_grp = p.add_mutually_exclusive_group()
    in_grp.add_argument("--wav", help="Source WAV (8 kHz mono 16-bit CVSD) — HS outbound")
    in_grp.add_argument(
        "--mic-device", type=int, default=None,
        help="sounddevice input device index for live mic capture (HS outbound)",
    )

    out_grp = p.add_mutually_exclusive_group()
    out_grp.add_argument("--out", help="Output WAV (HS inbound; optional)")
    out_grp.add_argument(
        "--speaker-device", type=int, default=None,
        help="sounddevice output device index for live playback",
    )

    # AG-side: WAV output; mutually exclusive with --speaker-device handled at runtime
    p.add_argument("--output", help="Output WAV (AG-side; required for --role=ag unless --speaker-device set)")

    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _hsp_test_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


def _build_sender(args, sco_link):
    """Return (kind, obj) for the outbound audio source, or (None, None)."""
    if args.mic_device is not None:
        from pybluehost.audio._sounddevice_io import AudioInputDevice
        from pybluehost.profiles.classic import MicToScoSender
        codec = getattr(sco_link, "codec", "CVSD")
        sr = 8000 if codec == "CVSD" else 16000
        blk = 240 if codec == "CVSD" else 120
        mic = AudioInputDevice(sample_rate=sr, channels=1, device=args.mic_device, buffer_frames=blk)
        return ("mic", (mic, MicToScoSender(audio_input=mic, sco_link=sco_link)))
    if getattr(args, "wav", None):
        return ("wav", WavToScoSender(wav_path=args.wav, sco_link=sco_link))
    return (None, None)


def _build_receiver(args, sco_link, *, ag_output: str | None = None):
    """Return (kind, obj) for the inbound audio sink, or (None, None)."""
    if args.speaker_device is not None:
        from pybluehost.audio._sounddevice_io import AudioOutputDevice
        from pybluehost.profiles.classic import ScoToSpeakerReceiver
        codec = getattr(sco_link, "codec", "CVSD")
        sr = 8000 if codec == "CVSD" else 16000
        blk = 240 if codec == "CVSD" else 120
        spk = AudioOutputDevice(sample_rate=sr, channels=1, device=args.speaker_device, buffer_frames=blk)
        return ("speaker", (spk, ScoToSpeakerReceiver(audio_output=spk, sco_link=sco_link)))
    wav_out = ag_output if ag_output is not None else getattr(args, "out", None)
    if wav_out:
        return ("wav", ScoToWavReceiver(wav_path=wav_out, sco_link=sco_link))
    return (None, None)


async def _hsp_test_main(stack: Stack, stop: asyncio.Event, args) -> None:
    if args.role == "hs":
        if not args.target:
            raise ValueError("--target is required for HS role")
        if not args.wav and args.mic_device is None:
            raise ValueError("HS role needs exactly one of --wav or --mic-device")
        await _run_hs(stack, args, stop)
    else:
        if not args.output and args.speaker_device is None:
            raise ValueError("AG role needs --output or --speaker-device")
        await _run_ag(stack, args, stop)


async def _run_hs(stack: Stack, args, stop: asyncio.Event) -> None:
    target = BDAddress.from_string(args.target)
    hs = HSPHeadset(stack=stack)
    hs.register()
    handle = await stack.connect_classic(target, timeout=10.0)
    await stack.authenticate_classic(handle, timeout=10.0)
    session = await hs.connect(handle=handle, channel=HSP_AG_RFCOMM_CHANNEL)
    await asyncio.sleep(0.1)
    await session.request_audio()
    await asyncio.sleep(0.1)
    sco_link = await session.setup_sco()

    snd_kind, snd = _build_sender(args, sco_link)
    rcv_kind, rcv = _build_receiver(args, sco_link)

    sender_task = None
    try:
        if rcv_kind == "speaker":
            spk_dev, _spk_recv = rcv
            await spk_dev.start()
        if snd_kind == "mic":
            mic_dev, mic_sender = snd
            await mic_dev.start()
            sender_task = asyncio.create_task(mic_sender.run())
            await stop.wait()    # live: wait until user stops
            await mic_sender.stop()
            await sender_task
        elif snd_kind == "wav":
            await snd.run()
            await asyncio.sleep(0.3)
    finally:
        if snd_kind == "mic":
            try:
                await snd[0].stop()
            except Exception:
                pass
        if rcv_kind == "speaker":
            try:
                await rcv[0].stop()
            except Exception:
                pass
        elif rcv_kind == "wav":
            rcv.close()
        await session.close()


async def _run_ag(stack: Stack, args, stop: asyncio.Event) -> None:
    ag = HSPAudioGateway(stack=stack)
    ag.register()
    logger.info(
        "HSP AG listening; output → %s. Ctrl+C to stop.",
        args.output if args.speaker_device is None else f"speaker:{args.speaker_device}",
    )
    receivers: list = []
    speaker_started = False

    async def stop_with_drain():
        await stop.wait()
        for r in receivers:
            if isinstance(r, ScoToWavReceiver):
                r.close()

    asyncio.create_task(stop_with_drain())
    seen: set[int] = set()
    while not stop.is_set():
        await asyncio.sleep(0.2)
        for _h, sess in list(ag._sessions.items()):
            sco = getattr(sess, "_sco_link", None)
            if sco is not None and id(sco) not in seen:
                seen.add(id(sco))
                rcv_kind, rcv = _build_receiver(args, sco, ag_output=args.output)
                if rcv_kind == "speaker":
                    spk_dev, spk_recv = rcv
                    if not speaker_started:
                        await spk_dev.start()
                        speaker_started = True
                    receivers.append(spk_recv)
                    logger.info("HSP AG armed speaker receiver on SCO handle 0x%04X", sco.handle)
                elif rcv_kind == "wav":
                    receivers.append(rcv)
                    logger.info("HSP AG armed WAV receiver on SCO handle 0x%04X", sco.handle)
