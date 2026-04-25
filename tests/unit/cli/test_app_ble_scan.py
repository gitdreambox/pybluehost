# tests/unit/cli/test_app_ble_scan.py
import asyncio
import pytest
from pybluehost.cli.app.ble_scan import _ble_scan_main
from pybluehost.stack import Stack


async def test_ble_scan_starts_and_stops_cleanly():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_ble_scan_main(stack, stop))
    asyncio.create_task(stopper())
    await task  # should return when stop.set
    await stack.close()
