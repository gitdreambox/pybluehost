"""'app sdp-browser' — connect, query SDP records, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._target import parse_target_arg
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.stack import Stack


def register_sdp_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("sdp-browser", help="Connect, query SDP, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help="BD_ADDR, e.g. A0:90:B5:10:40:82")
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(_sdp_browser_main(args)))


async def _sdp_browser_main(args: argparse.Namespace) -> int:
    if not args.target:
        print("Error: --target is required", file=sys.stderr)
        return 2

    addr, _atype = parse_target_arg(args.target)
    return await run_app_command(
        args.transport,
        lambda stack, stop: _sdp_browser_run(stack, stop, addr),
        **trace_kwargs_from_args(args),
    )


async def _sdp_browser_run(stack: Stack, stop: asyncio.Event, addr) -> None:
    del stack, stop
    print(f"Connecting to {addr}")
    raise RuntimeError("SDP query over BR/EDR ACL is not implemented")
