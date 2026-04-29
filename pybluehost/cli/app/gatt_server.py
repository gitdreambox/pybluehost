# pybluehost/cli/app/gatt_server.py
"""'app gatt-server' - register Battery + HRS, advertise, await connections."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.cli.app._ble_peripheral import start_connectable_advertising, stop_advertising
from pybluehost.profiles.ble import BatteryServer, HeartRateServer
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_gatt_server_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("gatt-server", help="Run Battery + HRS GATT server (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True)
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(args.transport, _gatt_server_main, **trace_kwargs_from_args(args))
    ))


async def _gatt_server_main(stack: Stack, stop: asyncio.Event) -> None:
    battery = BatteryServer(initial_level=85)
    hrs = HeartRateServer(sensor_location=0x02)
    await battery.register(stack.gatt_server)
    await hrs.register(stack.gatt_server)
    await start_connectable_advertising(
        stack,
        service_uuids=[0x180F, 0x180D],
        local_name="PyBlueHost GATT",
    )
    logger.info("GATT server up: BatteryServer + HeartRateServer registered")
    logger.info("Local address: %s", stack.local_address)
    logger.info("Advertising connectable BLE peripheral; Ctrl+C to stop")
    try:
        await stop.wait()
    finally:
        await stop_advertising(stack)
