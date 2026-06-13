"""'app demo-phone' — emulate a phone: A2DP Source + AVRCP Target + HFP AG.

The phone advertises all three profiles, accepts incoming connections, streams
a WAV file as A2DP audio when a headphone connects, responds to AVRCP commands
(play/pause/etc.), and optionally simulates an incoming call by emitting HFP
RING after a delay.

Pair this with `pybluehost app demo-headphone` for a full integrated demo
(virtual transport: run via VirtualClassicLink; real hardware: power both
adapters on, the headphone CLI does the connect).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import wave

from pybluehost.avrcp.constants import AVRCPEventID, AVRCPOperationID, AVRCPPlayStatus
from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.profiles.classic import (
    A2DPSource, AVRCPTarget, HFPAudioGateway,
)
from pybluehost.profiles.classic._at_parser import ATUnsolicited
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


def register_demo_phone_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "demo-phone",
        help="Phone-side integrated demo: A2DP Source + AVRCP Target + HFP AG",
    )
    add_common_arguments(p)
    p.add_argument(
        "--wav", required=True,
        help="WAV file (44.1 kHz stereo int16) to stream as A2DP music",
    )
    p.add_argument(
        "--ring-after", type=float, default=None,
        help="Seconds after startup to emit HFP RING (simulate incoming call)",
    )
    p.add_argument(
        "--caller", default="+15555550199",
        help="Caller ID for +CLIP (default: +15555550199)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _demo_phone_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _demo_phone_main(stack: Stack, stop: asyncio.Event, args) -> None:
    play_log = []

    # AVRCP Target — log every command + report PLAYING as current status
    async def on_pass_through(cmd) -> bool:
        try:
            name = AVRCPOperationID(cmd.operation_id).name
        except ValueError:
            name = f"OPID_0x{cmd.operation_id:02X}"
        if cmd.pressed:    # log only pressed half
            play_log.append(name)
            logger.info("[PHONE/AVRCP] command from headphone: %s", name)
        return True

    async def on_notify_register(event_id: int) -> bytes:
        try:
            name = AVRCPEventID(event_id).name
        except ValueError:
            name = f"EVT_0x{event_id:02X}"
        logger.info("[PHONE/AVRCP] subscription: %s", name)
        if event_id == AVRCPEventID.PLAYBACK_STATUS_CHANGED:
            return bytes([AVRCPPlayStatus.PLAYING])
        return b"\x00"

    avrcp_tgt = AVRCPTarget(
        stack=stack,
        on_pass_through=on_pass_through,
        on_notification_register=on_notify_register,
    )
    avrcp_tgt.register()
    logger.info("[PHONE] AVRCP Target registered (UUID 0x110C)")

    # A2DP Source — passive register. Active streaming happens via _stream_on_connect
    # which the e2e test or a real headphone connecting will trigger.
    src = A2DPSource(stack=stack)
    src.register()
    logger.info("[PHONE] A2DP Source registered (UUID 0x110A)")

    # HFP AG — passive register; on_call_event hook fires when headphone HF connects
    on_call_events: list[str] = []

    async def on_call_event(event: str) -> None:
        on_call_events.append(event)
        logger.info("[PHONE/HFP-AG] call event: %s", event)

    ag = HFPAudioGateway(stack=stack, on_call_event=on_call_event)
    ag.register()
    logger.info("[PHONE] HFP AG registered (UUID 0x111F)")

    # Background task: stream WAV to any A2DP session that connects.
    streamer_task = asyncio.create_task(_stream_to_peers(src, args.wav, stop))

    # Background task: emit RING after delay if requested.
    ring_task = None
    if args.ring_after is not None:
        ring_task = asyncio.create_task(
            _ring_after_delay(ag, args.ring_after, args.caller, stop),
        )

    logger.info("[PHONE] Ready. Waiting for headphone to connect. Ctrl+C to stop.")
    try:
        await stop.wait()
    finally:
        streamer_task.cancel()
        if ring_task is not None:
            ring_task.cancel()
        for t in (streamer_task, ring_task):
            if t is not None:
                try:
                    await t
                except asyncio.CancelledError:
                    pass


async def _stream_to_peers(src: A2DPSource, wav_path: str, stop: asyncio.Event) -> None:
    """Poll src._sessions; for each session that hits STREAMING, push WAV frames."""
    streamed_handles: set[int] = set()
    while not stop.is_set():
        await asyncio.sleep(0.2)
        for handle, session in list(src._sessions.items()):
            if handle in streamed_handles:
                continue
            # Wait until the AVDTP session reaches a state where send_pcm is safe.
            if getattr(session, "_encoder", None) is None:
                continue
            streamed_handles.add(handle)
            asyncio.create_task(_push_wav(session, wav_path, stop))
            logger.info("[PHONE/A2DP] streaming '%s' to handle 0x%04X", wav_path, handle)


async def _push_wav(session, wav_path: str, stop: asyncio.Event) -> None:
    bytes_per_frame = 2 * 16 * 8 * 2   # 512 bytes per encode
    try:
        with wave.open(wav_path, "rb") as w:
            while not stop.is_set():
                pcm = w.readframes(256)
                if len(pcm) < bytes_per_frame:
                    break
                try:
                    await session.send_pcm(pcm)
                except Exception:
                    return
                await asyncio.sleep(0)
    finally:
        logger.info("[PHONE/A2DP] WAV exhausted; stopping stream")


async def _ring_after_delay(
    ag: HFPAudioGateway, delay: float, caller: str, stop: asyncio.Event,
) -> None:
    await asyncio.sleep(delay)
    if stop.is_set():
        return
    # Find an active HFP session and emit RING + +CLIP.
    if not ag._sessions:
        logger.warning("[PHONE/HFP-AG] no active HFP session at ring time")
        return
    for session in ag._sessions.values():
        try:
            await session._send_at(ATUnsolicited(name="RING", args=[]))
            await session._send_at(ATUnsolicited(name="+CLIP", args=[f'"{caller}"', "129"]))
            logger.info("[PHONE/HFP-AG] RING + CLIP %s sent", caller)
        except Exception as exc:
            logger.warning("[PHONE/HFP-AG] failed to emit RING: %s", exc)
