"""'tools decode' — decode an H4 HCI packet from hex string."""
from __future__ import annotations

import argparse
import logging

from pybluehost.hci.packets import decode_hci_packet

logger = logging.getLogger(__name__)


def register_decode_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("decode", help="Decode an HCI packet from hex")
    p.add_argument("hex", help="Hex string of an H4 HCI packet (e.g. 01030c00)")
    p.set_defaults(func=_cmd_decode)


def _cmd_decode(args: argparse.Namespace) -> int:
    s = args.hex.strip().replace(" ", "").replace(":", "")
    if not s:
        logger.error("Error: empty hex string")
        return 1
    try:
        data = bytes.fromhex(s)
    except ValueError as e:
        logger.error("Error: invalid hex: %s", e)
        return 1
    try:
        pkt = decode_hci_packet(data)
    except Exception as e:
        logger.error("Error: decode failed: %s", e)
        return 1
    logger.info(type(pkt).__name__)
    for field in pkt.__dataclass_fields__ if hasattr(pkt, "__dataclass_fields__") else []:
        val = getattr(pkt, field)
        if isinstance(val, int):
            logger.info("  %-20s 0x%X", field, val)
        elif isinstance(val, bytes):
            logger.info("  %-20s %s", field, val.hex())
        else:
            logger.info("  %-20s %r", field, val)
    return 0
