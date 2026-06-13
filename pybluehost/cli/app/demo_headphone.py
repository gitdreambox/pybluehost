"""'app demo-headphone' — emulate a wireless headphone: A2DP Sink + AVRCP Controller + HFP HF.

The headphone pairs to the target phone, connects all three profiles, and
optionally issues an AVRCP command after a delay and/or answers an incoming
HFP call when RING arrives.

Pair this with `pybluehost app demo-phone` for a full integrated demo.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import wave

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.address import BDAddress
from pybluehost.profiles.classic import (
    A2DPSink, AVRCPController, HFPHandsFree,
)
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


_AVRCP_METHODS = {
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "next": "next_track",
    "prev": "prev_track",
    "vol-up": "volume_up",
    "vol-down": "volume_down",
}


def register_demo_headphone_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "demo-headphone",
        help="Headphone-side integrated demo: A2DP Sink + AVRCP Controller + HFP HF",
    )
    add_common_arguments(p)
    p.add_argument("--target", required=True, help="Phone BD_ADDR (AA:BB:CC:DD:EE:FF)")
    p.add_argument(
        "--output", default="received_music.wav",
        help="WAV path for received A2DP audio (default: received_music.wav)",
    )
    p.add_argument(
        "--avrcp-cmd", choices=sorted(_AVRCP_METHODS.keys()), default=None,
        help="If set, issue this AVRCP command after --avrcp-cmd-at seconds",
    )
    p.add_argument(
        "--avrcp-cmd-at", type=float, default=2.0,
        help="Seconds after connect to send --avrcp-cmd (default: 2.0)",
    )
    p.add_argument(
        "--auto-answer", action="store_true",
        help="Set up SCO and write received call audio when RING is observed",
    )
    p.add_argument(
        "--call-output", default="received_call.wav",
        help="WAV path for received HFP call audio (when --auto-answer)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _demo_headphone_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _demo_headphone_main(stack: Stack, stop: asyncio.Event, args) -> None:
    target = BDAddress.from_string(args.target)

    # --- A2DP Sink (receives music) ----------------------------------
    music_wav = wave.open(args.output, "wb")
    music_wav.setnchannels(2)
    music_wav.setsampwidth(2)
    music_wav.setframerate(44100)

    pcm_chunks_received = []

    async def on_pcm(pcm: bytes) -> None:
        music_wav.writeframes(pcm)
        pcm_chunks_received.append(len(pcm))
        if len(pcm_chunks_received) == 1:
            logger.info("[HEADPHONE/A2DP] first audio frame received (%d bytes)", len(pcm))

    sink = A2DPSink(stack=stack, on_pcm=on_pcm)
    sink.register()
    logger.info("[HEADPHONE] A2DP Sink registered, writing to %s", args.output)

    # --- HFP HF (receives RING/calls) --------------------------------
    hfp_hf = HFPHandsFree(stack=stack)
    hfp_hf.register()
    logger.info("[HEADPHONE] HFP HF registered (UUID 0x111E)")

    # --- Pair + connect to phone -------------------------------------
    handle = await stack.connect_classic(target, timeout=10.0)
    await stack.authenticate_classic(handle, timeout=10.0)
    logger.info("[HEADPHONE] paired + authenticated with %s (handle 0x%04X)", target, handle)

    # --- AVRCP Controller (sends commands) ----------------------------
    avrcp_ctrl = AVRCPController(stack=stack)
    avrcp_ctrl.register()
    avrcp_session = await avrcp_ctrl.connect(handle=handle)
    await asyncio.sleep(0.1)
    logger.info("[HEADPHONE] AVRCP Controller connected")

    # Scheduled AVRCP command
    avrcp_task = None
    if args.avrcp_cmd is not None:
        avrcp_task = asyncio.create_task(
            _send_avrcp_after_delay(avrcp_session, args.avrcp_cmd, args.avrcp_cmd_at, stop),
        )

    # HFP HF connect (also opens RFCOMM channel)
    hfp_session = None
    try:
        hfp_session = await hfp_hf.connect(handle=handle)
        await asyncio.sleep(0.1)
        logger.info(
            "[HEADPHONE] HFP HF SLC %s",
            hfp_session.sm.state.name if hfp_session.sm else "n/a",
        )
    except Exception as exc:
        logger.warning("[HEADPHONE] HFP HF connect failed: %s", exc)

    # If --auto-answer, watch for SCO link arming (phone-side AG sets up SCO).
    call_wav_task = None
    if args.auto_answer and hfp_session is not None:
        call_wav_task = asyncio.create_task(
            _drain_call_to_wav(hfp_session, args.call_output, stop),
        )

    logger.info("[HEADPHONE] Demo running. Ctrl+C to stop.")
    try:
        await stop.wait()
    finally:
        if avrcp_task is not None:
            avrcp_task.cancel()
        if call_wav_task is not None:
            call_wav_task.cancel()
        for t in (avrcp_task, call_wav_task):
            if t is not None:
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        try:
            await avrcp_session.close()
        except Exception:
            pass
        if hfp_session is not None:
            try:
                await hfp_session.close()
            except Exception:
                pass
        music_wav.close()
        logger.info(
            "[HEADPHONE] Stopped. Received %d A2DP chunks (%d bytes)",
            len(pcm_chunks_received), sum(pcm_chunks_received),
        )


async def _send_avrcp_after_delay(
    session, cmd: str, delay: float, stop: asyncio.Event,
) -> None:
    await asyncio.sleep(delay)
    if stop.is_set():
        return
    method = getattr(session, _AVRCP_METHODS[cmd])
    try:
        ok = await method()
        logger.info(
            "[HEADPHONE/AVRCP] sent %s → %s",
            cmd, "ACCEPTED" if ok else "NOT_IMPLEMENTED/REJECTED",
        )
    except Exception as exc:
        logger.warning("[HEADPHONE/AVRCP] %s failed: %s", cmd, exc)


async def _drain_call_to_wav(hfp_session, wav_path: str, stop: asyncio.Event) -> None:
    """If a SCO link comes up on the HF session, write its decoded PCM to a WAV."""
    from pybluehost.profiles.classic._sco_loopback import ScoToWavReceiver
    # Poll for SCO link to appear (phone AG sets it up after RING/answer).
    while not stop.is_set():
        await asyncio.sleep(0.2)
        sco = getattr(hfp_session, "_sco_link", None)
        if sco is None:
            continue
        logger.info("[HEADPHONE/HFP-HF] SCO link armed (handle 0x%04X, codec %s) → %s",
                    sco.handle, sco.codec, wav_path)
        receiver = ScoToWavReceiver(wav_path=wav_path, sco_link=sco)
        try:
            await stop.wait()
        finally:
            receiver.close()
        return
