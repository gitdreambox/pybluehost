"""'app sdp-browser' — connect, query SDP records, print, exit."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pybluehost.cli._target import parse_target_arg
from pybluehost.cli._transport import parse_transport_arg
from pybluehost.stack import Stack


def register_sdp_browser_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("sdp-browser", help="Connect, query SDP, print, exit")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-a", "--target", help="BD_ADDR")
    p.set_defaults(func=lambda args: asyncio.run(_sdp_browser_main(args)))


async def _sdp_browser_main(args: argparse.Namespace) -> int:
    if not args.target:
        print("Error: --target is required", file=sys.stderr)
        return 2

    addr, _atype = parse_target_arg(args.target)
    try:
        transport = await parse_transport_arg(args.transport)
        stack = await Stack._build(transport=transport)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        print(f"Connecting to {addr}")
        print("Error: SDP query over BR/EDR ACL is not implemented", file=sys.stderr)
        return 1
    finally:
        await stack.close()
