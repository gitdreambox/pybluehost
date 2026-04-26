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
    p.add_argument("--transport", required=True)
    p.add_argument("--target", help="BD_ADDR (required unless --transport loopback)")
    p.set_defaults(func=lambda args: asyncio.run(_sdp_browser_main(args)))


async def _sdp_browser_main(args: argparse.Namespace) -> int:
    is_loopback = args.transport == "loopback"
    if not is_loopback and not args.target:
        print("Error: --target is required for non-loopback transport", file=sys.stderr)
        return 2

    try:
        transport = await parse_transport_arg(args.transport)
        stack = await Stack._build(transport=transport)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        if is_loopback:
            print("SDP records (loopback peer):")
            peer_sdp = stack.sdp
            # SDPServer stores records in _records dict[int, ServiceRecord]
            records = list(peer_sdp._records.values())
            if not records:
                print("  (no records registered)")
            for rec in records:
                print(f"  Record handle=0x{rec.handle:08X}")
        else:
            addr, _atype = parse_target_arg(args.target)
            print(f"Connected to {addr}")
            print("(Real-hardware SDP query not implemented in v1; loopback only.)")
        return 0
    finally:
        await stack.close()
