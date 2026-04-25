import asyncio
import pytest
from pybluehost.cli._lifecycle import run_app_command


async def test_run_app_command_completes_normally():
    async def main(stack, stop):
        return

    code = await run_app_command("loopback", main)
    assert code == 0


async def test_run_app_command_returns_when_main_finishes():
    """If main returns before stop_event fires, exit 0."""
    async def main(stack, stop):
        # Just returns immediately
        return

    code = await run_app_command("loopback", main)
    assert code == 0


async def test_run_app_command_propagates_error():
    async def main(stack, stop):
        raise RuntimeError("boom")

    code = await run_app_command("loopback", main)
    assert code == 1


async def test_run_app_command_invalid_transport():
    async def main(stack, stop):
        return

    code = await run_app_command("bogus", main)
    assert code == 1
