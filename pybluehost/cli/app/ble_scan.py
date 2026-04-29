# pybluehost/cli/app/ble_scan.py
"""'app ble-scan' — long-running BLE advertisement scan."""
from __future__ import annotations

import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import add_trace_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.stack import Stack

logger = logging.getLogger(__name__)


def register_ble_scan_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ble-scan", help="Scan BLE advertisements (Ctrl+C to stop)")
    p.add_argument("-t", "--transport", required=True, help="virtual | usb[:vendor=...] | uart:/dev/...[@baud]")
    add_trace_arguments(p)
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            _ble_scan_main,
            **trace_kwargs_from_args(args),
        )
    ))


async def _ble_scan_main(stack: Stack, stop: asyncio.Event) -> None:
    seen: dict[str, int] = {}

    def on_result(result):
        addr_s = str(result.address)
        rssi = result.rssi
        if addr_s not in seen or abs(seen[addr_s] - rssi) > 5:
            name = getattr(result, "local_name", None) or "<no name>"
            logger.info("%s  rssi=%4s  %s", addr_s, rssi, name)
            seen[addr_s] = rssi

    stack.gap.ble_scanner.on_result(on_result)
    await stack.gap.ble_scanner.start()
    logger.info("Scanning BLE advertisements... Ctrl+C to stop")
    try:
        await stop.wait()
    finally:
        await stack.gap.ble_scanner.stop()
