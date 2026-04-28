import asyncio
from pybluehost.cli.app.gatt_server import _gatt_server_main


async def test_gatt_server_registers_battery_and_hrs(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_gatt_server_main(stack, stop))
    asyncio.create_task(stopper())
    await task
