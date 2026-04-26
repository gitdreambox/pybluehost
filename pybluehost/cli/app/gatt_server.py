# pybluehost/cli/app/gatt_server.py
"""'app gatt-server' — register Battery + HRS, await connections."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.profiles.ble import BatteryServer, HeartRateServer
from pybluehost.stack import Stack


def register_gatt_server_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-server", help="Run Battery + HRS GATT server (Ctrl+C to stop)")
    p.add_argument("--transport", required=True)
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _gatt_server_main)))


async def _gatt_server_main(stack: Stack, stop: asyncio.Event) -> None:
    battery = BatteryServer(initial_level=85)
    hrs = HeartRateServer(sensor_location=0x02)
    await battery.register(stack.gatt_server)
    await hrs.register(stack.gatt_server)
    print(f"GATT server up: BatteryServer + HeartRateServer registered")
    print(f"Local address: {stack.local_address}")
    print("Awaiting connections — Ctrl+C to stop")
    await stop.wait()
