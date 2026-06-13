"""'app avrcp-target' — passive AVRCP target; logs each incoming command."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.avrcp.constants import AVRCPEventID, AVRCPOperationID, AVRCPPlayStatus
from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)
from pybluehost.profiles.classic import AVRCPTarget
from pybluehost.stack import Stack


logger = logging.getLogger(__name__)


def register_avrcp_target_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "avrcp-target",
        help="Listen for incoming AVRCP commands (PASS_THROUGH + REGISTER_NOTIFICATION); log each",
    )
    add_common_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            _avrcp_target_main,
            **trace_kwargs_from_args(args),
            trace_spec=getattr(args, "_trace_spec", None),
        )
    ))


async def _avrcp_target_main(stack: Stack, stop: asyncio.Event) -> None:
    async def on_pass_through(cmd) -> bool:
        try:
            name = AVRCPOperationID(cmd.operation_id).name
        except ValueError:
            name = f"OPID_0x{cmd.operation_id:02X}"
        state = "pressed" if cmd.pressed else "released"
        logger.info("AVRCP <- %s %s", name, state)
        return True

    async def on_notify_register(event_id: int) -> bytes:
        try:
            name = AVRCPEventID(event_id).name
        except ValueError:
            name = f"EVT_0x{event_id:02X}"
        logger.info("AVRCP <- subscribe %s", name)
        if event_id == AVRCPEventID.PLAYBACK_STATUS_CHANGED:
            return bytes([AVRCPPlayStatus.PLAYING])
        return b"\x00"

    target = AVRCPTarget(
        stack=stack,
        on_pass_through=on_pass_through,
        on_notification_register=on_notify_register,
    )
    target.register()
    logger.info("AVRCP target registered. Ctrl+C to stop.")
    await stop.wait()
