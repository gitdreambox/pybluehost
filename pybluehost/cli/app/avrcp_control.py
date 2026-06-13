"""'app avrcp-control' — issue a one-shot AVRCP PASS_THROUGH command to a peer."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.core.address import BDAddress
from pybluehost.profiles.classic import AVRCPController
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


_CMD_TABLE = {
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "next": "next_track",
    "prev": "prev_track",
    "vol-up": "volume_up",
    "vol-down": "volume_down",
}


def register_avrcp_control_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "avrcp-control",
        help="Send one AVRCP PASS_THROUGH command (play/pause/stop/next/prev/vol-up/vol-down)",
    )
    add_common_arguments(p)
    p.add_argument("--target", required=True, help="Peer BD_ADDR (AA:BB:CC:DD:EE:FF)")
    p.add_argument(
        "--cmd", dest="cmd_action", required=True,
        choices=sorted(_CMD_TABLE.keys()),
        help="Operation to send",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _avrcp_control_main(stack, stop, args),
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _avrcp_control_main(stack: Stack, stop: asyncio.Event, args) -> None:
    target = BDAddress.from_string(args.target)
    ctrl = AVRCPController(stack=stack)
    ctrl.register()

    handle = await stack.connect_classic(target, timeout=10.0)
    await stack.authenticate_classic(handle, timeout=10.0)
    session = await ctrl.connect(handle=handle)
    await asyncio.sleep(0.2)

    method_name = _CMD_TABLE[args.cmd_action]
    method = getattr(session, method_name)
    ok = await method()
    logger.info("avrcp %s → %s", args.cmd_action, "ACCEPTED" if ok else "NOT_IMPLEMENTED/REJECTED")
    await session.close()
