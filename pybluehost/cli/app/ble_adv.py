# pybluehost/cli/app/ble_adv.py
"""'app ble-adv' - start BLE advertising until Ctrl+C."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.ble.gap import AdvertisingConfig
from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_ble_adv_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ble-adv", help="Advertise BLE (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True)
    p.add_argument("-n", "--name", default="PyBlueHost", help="Local name in advertising data")
    add_trace_arguments(p)
    p.set_defaults(
        func=lambda args: asyncio.run(
            run_app_command(
                args.transport,
                lambda s, e: _ble_adv_main(s, e, name=args.name),
                **trace_kwargs_from_args(args),
            )
        )
    )


async def _ble_adv_main(stack: Stack, stop: asyncio.Event, *, name: str) -> None:
    config = AdvertisingConfig()
    ad_data = AdvertisingData()
    ad_data.set_complete_local_name(name)
    await stack.gap.ble_advertiser.start(config, ad_data=ad_data)
    logger.info("Advertising as %r - Ctrl+C to stop", name)
    try:
        await stop.wait()
    finally:
        await stack.gap.ble_advertiser.stop()
