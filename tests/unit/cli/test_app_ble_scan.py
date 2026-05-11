# tests/unit/cli/test_app_ble_scan.py
import argparse
import asyncio
from pathlib import Path

import pytest
from pybluehost.cli.app.ble_scan import _ble_scan_main, register_ble_scan_command
from pybluehost.core.errors import CommandTimeoutError


async def test_ble_scan_starts_and_stops_cleanly(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_ble_scan_main(stack, stop))
    asyncio.create_task(stopper())
    await task  # should return when stop.set


async def test_ble_scan_suppresses_stop_timeout_during_shutdown():
    class Scanner:
        def on_result(self, handler):
            self.handler = handler

        async def start(self):
            return

        async def stop(self):
            raise CommandTimeoutError("HCI command 0x200C timed out after 5.0s")

    class Gap:
        ble_scanner = Scanner()

    class Stack:
        gap = Gap()

    stop = asyncio.Event()
    stop.set()

    await _ble_scan_main(Stack(), stop)


def test_ble_scan_accepts_btsnoop_option():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_ble_scan_command(subparsers)

    args = parser.parse_args(
        ["ble-scan", "-t", "usb:vendor=csr", "--btsnoop", "scan.cfa"]
    )

    assert args.transport == "usb:vendor=csr"
    assert args.btsnoop == Path("scan.cfa")
