"""'app classic-inquiry' — looped Classic inquiry, dedup-print results."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.classic.gap import InquiryConfig
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_classic_inquiry_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("classic-inquiry", help="Loop Classic inquiry (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(args.transport, _classic_inquiry_main, **trace_kwargs_from_args(args))
    ))


async def _classic_inquiry_main(stack: Stack, stop: asyncio.Event) -> None:
    seen: set[str] = set()

    def on_result(info):
        addr_s = str(info.address)
        if addr_s not in seen:
            name = getattr(info, "name", None) or "<unknown>"
            cod = getattr(info, "class_of_device", 0)
            logger.info("%s  CoD=0x%06X  %s", addr_s, cod, name)
            seen.add(addr_s)

    stack.gap.classic_discovery.on_result(on_result)
    config = InquiryConfig(duration=8)

    while not stop.is_set():
        try:
            await stack.gap.classic_discovery.start(config)
        except Exception as e:
            logger.error("Inquiry error: %s", e)
            break
        # Wait either inquiry duration or stop, whichever first
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.duration * 1.28)
        except asyncio.TimeoutError:
            pass
        await stack.gap.classic_discovery.stop()
