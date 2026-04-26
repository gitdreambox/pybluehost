"""'app hr-monitor' — HRS server pushing random heart-rate notifications."""
from __future__ import annotations

import argparse
import asyncio
import random

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.profiles.ble import HeartRateServer
from pybluehost.stack import Stack


def register_hr_monitor_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("hr-monitor", help="HRS server pushing random heart-rate (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _hr_monitor_main)))


async def _hr_monitor_main(stack: Stack, stop: asyncio.Event, *, interval: float = 1.0) -> None:
    hrs = HeartRateServer(sensor_location=0x02)
    await hrs.register(stack.gatt_server)
    print(f"HRS up at {stack.local_address} — pushing random bpm every {interval}s")

    while not stop.is_set():
        bpm = random.randint(60, 100)
        await hrs.update_measurement(bpm=bpm)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
