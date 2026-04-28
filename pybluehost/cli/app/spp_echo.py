"""'app spp-echo' - RFCOMM channel 1 echo server."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.classic.spp import SPPConnection, SPPService
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.stack import Stack


def register_spp_echo_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("spp-echo", help="RFCOMM ch1 echo server (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(args.transport, _spp_echo_main, **trace_kwargs_from_args(args))
    ))


async def _spp_echo_main(stack: Stack, stop: asyncio.Event) -> None:
    service = SPPService(rfcomm=stack.rfcomm, sdp=stack.sdp)

    async def _echo_handler(conn: SPPConnection) -> None:
        while not stop.is_set():
            data = await conn.recv()
            await conn.send(data)

    service.on_connection(_echo_handler)
    await service.register(channel=1, name="PyBlueHost SPP Echo")
    print(f"SPP echo server listening on RFCOMM channel 1; local={stack.local_address}")
    await stop.wait()
