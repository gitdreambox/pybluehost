import asyncio
from pybluehost.cli.app.hr_monitor import _hr_monitor_main


async def test_hr_monitor_pushes_measurements_until_stop(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.15)
        stop.set()

    task = asyncio.create_task(_hr_monitor_main(stack, stop, interval=0.05))
    asyncio.create_task(stopper())
    await task
