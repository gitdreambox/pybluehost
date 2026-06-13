"""'app hfp-test' — HFP SCO loopback test (WAV in/out)."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.address import BDAddress
from pybluehost.profiles.classic import HFPAudioGateway, HFPHandsFree
from pybluehost.profiles.classic._sco_loopback import (
    ScoToWavReceiver, WavToScoSender,
)
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


def register_hfp_test_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "hfp-test",
        help="HFP SCO loopback test — HF pushes WAV / AG receives WAV",
    )
    add_common_arguments(p)
    p.add_argument("--role", required=True, choices=["hf", "ag"])
    p.add_argument("--target", help="Peer BD_ADDR (required when --role=hf)")
    p.add_argument("--wav", help="Source WAV (required for --role=hf)")
    p.add_argument("--out", help="Output WAV (HF-side; optional)")
    p.add_argument("--output", help="Output WAV (AG-side; required for --role=ag)")
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _hfp_test_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _hfp_test_main(stack: Stack, stop: asyncio.Event, args) -> None:
    if args.role == "hf":
        if not args.target or not args.wav:
            raise ValueError("--target and --wav are required for HF role")
        await _run_hf(stack, args, stop)
    else:
        if not args.output:
            raise ValueError("--output is required for AG role")
        await _run_ag(stack, args, stop)


async def _run_hf(stack: Stack, args, stop: asyncio.Event) -> None:
    target = BDAddress.from_string(args.target)
    hf = HFPHandsFree(stack=stack)
    hf.register()
    handle = await stack.connect_classic(target, timeout=10.0)
    await stack.authenticate_classic(handle, timeout=10.0)
    session = await hf.connect(handle=handle)
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
    ag = HFPAudioGateway(stack=stack)
    ag.register()
    logger.info("HFP AG listening; output → %s. Ctrl+C to stop.", args.output)
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
                logger.info("HFP AG armed receiver on SCO handle 0x%04X", sco.handle)
