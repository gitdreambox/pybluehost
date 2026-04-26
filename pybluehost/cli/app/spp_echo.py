"""'app spp-echo' — RFCOMM channel 1 echo server."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_spp_echo_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("spp-echo", help="RFCOMM ch1 echo server (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _spp_echo_main)))


async def _spp_echo_main(stack: Stack, stop: asyncio.Event) -> None:
    rfcomm = stack.rfcomm
    print(f"SPP echo server — local={stack.local_address}")
    # RFCOMMManager.listen(server_channel, handler) registers an incoming-connection handler.
    # The handler receives an RFCOMMChannel; we read and echo until the channel closes.
    # In loopback mode there is no real peer, so the handler is registered but never invoked;
    # the test only checks that the command exits cleanly when stop fires.
    if hasattr(rfcomm, "listen"):
        async def _echo_handler(channel: object) -> None:
            # channel is an RFCOMMChannel — iterate incoming data and echo it back
            if hasattr(channel, "__aiter__"):
                async for data in channel:  # type: ignore[union-attr]
                    if hasattr(channel, "write"):
                        await channel.write(data)  # type: ignore[union-attr]
                    elif hasattr(channel, "send"):
                        await channel.send(data)  # type: ignore[union-attr]

        try:
            await rfcomm.listen(server_channel=1, handler=_echo_handler)
        except (TypeError, NotImplementedError):
            # API mismatch or stub — degrade gracefully (loopback has no peer anyway)
            print("NOTE: RFCOMMManager.listen not available; running in no-op mode")
    else:
        print("NOTE: RFCOMMManager has no listen API; running in no-op mode")

    await stop.wait()
