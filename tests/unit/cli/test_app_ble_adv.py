import argparse
import asyncio
from pathlib import Path

import pytest
from pybluehost.cli.app.ble_adv import _ble_adv_main, register_ble_adv_command


async def test_ble_adv_starts_and_stops_cleanly(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    args_name = "PyBlueHostTest"
    task = asyncio.create_task(_ble_adv_main(stack, stop, name=args_name))
    asyncio.create_task(stopper())
    await task


def test_ble_adv_accepts_trace_options():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_ble_adv_command(subparsers)

    args = parser.parse_args(
        [
            "ble-adv",
            "-t",
            "usb:vendor=csr",
            "-n",
            "TraceTest",
            "--hci-log",
            "--btsnoop",
            "adv.cfa",
        ]
    )

    assert args.transport == "usb:vendor=csr"
    assert args.name == "TraceTest"
    assert args.hci_log is True
    assert args.btsnoop == Path("adv.cfa")
