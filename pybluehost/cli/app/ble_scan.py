# pybluehost/cli/app/ble_scan.py
"""'app ble-scan' — long-running BLE advertisement scan."""
from __future__ import annotations

import argparse
import asyncio

from pybluehost.cli._lifecycle import run_app_command
from pybluehost.stack import Stack


def register_ble_scan_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ble-scan", help="Scan BLE advertisements (Ctrl+C to stop)")
    p.add_argument("--transport", required=True, help="loopback | usb[:vendor=...] | uart:/dev/...[@baud]")
    p.set_defaults(func=lambda args: asyncio.run(run_app_command(args.transport, _ble_scan_main)))


async def _ble_scan_main(stack: Stack, stop: asyncio.Event) -> None:
    seen: dict[str, int] = {}

    def on_result(result):
        addr_s = str(result.address)
        rssi = result.rssi
        if addr_s not in seen or abs(seen[addr_s] - rssi) > 5:
            name = getattr(result, "local_name", None) or "<no name>"
            print(f"{addr_s}  rssi={rssi:>4}  {name}")
            seen[addr_s] = rssi

    stack.gap.ble_scanner.on_result(on_result)
    await stack.gap.ble_scanner.start()
    try:
        await stop.wait()
    finally:
        await stack.gap.ble_scanner.stop()
