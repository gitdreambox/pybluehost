"""'app hsp-test' — HSP SCO loopback test (WAV in/out, CVSD-only)."""
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
        help="HSP SCO loopback test — HS pushes WAV / AG receives WAV",
    )
    add_common_arguments(p)
    p.add_argument("--role", required=True, choices=["hs", "ag"])
    p.add_argument("--target", help="Peer BD_ADDR (required when --role=hs)")
    p.add_argument("--wav", help="Source WAV (8 kHz mono 16-bit CVSD) — required for --role=hs")
    p.add_argument("--out", help="Output WAV (HS-side; optional)")
    p.add_argument("--output", help="Output WAV (AG-side; required for --role=ag)")
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _hsp_test_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _hsp_test_main(stack: Stack, stop: asyncio.Event, args) -> None:
    if args.role == "hs":
        if not args.target or not args.wav:
            raise ValueError("--target and --wav are required for HS role")
        await _run_hs(stack, args, stop)
    else:
        if not args.output:
            raise ValueError("--output is required for AG role")
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
    sender = WavToScoSender(wav_path=args.wav, sco_link=sco_link)
    receiver = None
    if args.out:
        receiver = ScoToWavReceiver(wav_path=args.out, sco_link=sco_link)
    try:
        await sender.run()
        await asyncio.sleep(0.3)
    finally:
        if receiver is not None:
            receiver.close()
        await session.close()


async def _run_ag(stack: Stack, args, stop: asyncio.Event) -> None:
    ag = HSPAudioGateway(stack=stack)
    ag.register()
    logger.info("HSP AG listening; output → %s. Ctrl+C to stop.", args.output)
    receivers: list[ScoToWavReceiver] = []

    async def stop_with_drain():
        await stop.wait()
        for r in receivers:
            r.close()

    asyncio.create_task(stop_with_drain())
    seen: set[int] = set()
    while not stop.is_set():
        await asyncio.sleep(0.2)
        for _h, sess in list(ag._sessions.items()):
            sco = getattr(sess, "_sco_link", None)
            if sco is not None and id(sco) not in seen:
                seen.add(id(sco))
                receivers.append(ScoToWavReceiver(wav_path=args.output, sco_link=sco))
                logger.info("HSP AG armed receiver on SCO handle 0x%04X", sco.handle)
