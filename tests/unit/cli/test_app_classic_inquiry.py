import asyncio
import pytest
from pybluehost.cli.app.classic_inquiry import _classic_inquiry_main


async def test_classic_inquiry_loops_and_stops(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_classic_inquiry_main(stack, stop))
    asyncio.create_task(stopper())
    await task
