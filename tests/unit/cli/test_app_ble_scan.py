# tests/unit/cli/test_app_ble_scan.py
import argparse
import asyncio
from pathlib import Path

import pytest
from pybluehost.cli.app.ble_scan import _ble_scan_main, register_ble_scan_command


async def test_ble_scan_starts_and_stops_cleanly(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_ble_scan_main(stack, stop))
    asyncio.create_task(stopper())
    await task  # should return when stop.set


def test_ble_scan_accepts_btsnoop_option():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_ble_scan_command(subparsers)

    args = parser.parse_args(
        ["ble-scan", "-t", "usb:vendor=csr", "--btsnoop", "scan.cfa"]
    )

    assert args.transport == "usb:vendor=csr"
    assert args.btsnoop == Path("scan.cfa")
