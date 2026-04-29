"""'app hr-monitor' - HRS server pushing heart-rate notifications."""
from __future__ import annotations

import argparse
import asyncio
import logging
import random

from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.cli.app._ble_peripheral import start_connectable_advertising, stop_advertising
from pybluehost.profiles.ble import HeartRateServer
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_hr_monitor_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("hr-monitor", help="HRS server pushing random heart-rate (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(args.transport, _hr_monitor_main, **trace_kwargs_from_args(args))
    ))


async def _hr_monitor_main(stack: Stack, stop: asyncio.Event, *, interval: float = 1.0) -> None:
    hrs = HeartRateServer(sensor_location=0x02)
    await hrs.register(stack.gatt_server)
    await start_connectable_advertising(
        stack,
        service_uuids=[0x180D],
        local_name="PyBlueHost HR",
    )
    logger.info(
        "HRS up at %s; advertising and pushing random bpm every %ss",
        stack.local_address,
        interval,
    )

    try:
        while not stop.is_set():
            bpm = random.randint(60, 100)
            await hrs.update_measurement(bpm=bpm)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await stop_advertising(stack)
