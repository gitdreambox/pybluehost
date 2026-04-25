import asyncio
import pytest
from pybluehost.cli.app.ble_adv import _ble_adv_main
from pybluehost.stack import Stack


async def test_ble_adv_starts_and_stops_cleanly():
    stack = await Stack.loopback()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    args_name = "PyBlueHostTest"
    task = asyncio.create_task(_ble_adv_main(stack, stop, name=args_name))
    asyncio.create_task(stopper())
    await task
    await stack.close()
