"""'tools decode' — decode an H4 HCI packet from hex string."""
from __future__ import annotations

import argparse
import sys

from pybluehost.hci.packets import decode_hci_packet


def register_decode_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("decode", help="Decode an HCI packet from hex")
    p.add_argument("hex", help="Hex string of an H4 HCI packet (e.g. 01030c00)")
    p.set_defaults(func=_cmd_decode)


def _cmd_decode(args: argparse.Namespace) -> int:
    s = args.hex.strip().replace(" ", "").replace(":", "")
    if not s:
        print("Error: empty hex string", file=sys.stderr)
        return 1
    try:
        data = bytes.fromhex(s)
    except ValueError as e:
        print(f"Error: invalid hex: {e}", file=sys.stderr)
        return 1
    try:
        pkt = decode_hci_packet(data)
    except Exception as e:
        print(f"Error: decode failed: {e}", file=sys.stderr)
        return 1
    print(type(pkt).__name__)
    for field in pkt.__dataclass_fields__ if hasattr(pkt, "__dataclass_fields__") else []:
        val = getattr(pkt, field)
        if isinstance(val, int):
            print(f"  {field:20s} 0x{val:X}")
        elif isinstance(val, bytes):
            print(f"  {field:20s} {val.hex()}")
        else:
            print(f"  {field:20s} {val!r}")
    return 0
