import asyncio
from pybluehost.cli.app.spp_echo import _spp_echo_main
from pybluehost.stack import Stack


async def test_spp_echo_starts_and_stops_cleanly():
    stack = await Stack.virtual()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_spp_echo_main(stack, stop))
    asyncio.create_task(stopper())
    await task
    await stack.close()
