import asyncio
from pybluehost.ble.gatt import GATTServer
from pybluehost.cli.app.gatt_server import _gatt_server_main


class FakeAdvertiser:
    def __init__(self):
        self.started = []
        self.stopped = False

    async def start(self, config, ad_data, scan_rsp_data=None):
        self.started.append((config, ad_data, scan_rsp_data))

    async def stop(self):
        self.stopped = True


class FakeGap:
    def __init__(self):
        self.ble_advertiser = FakeAdvertiser()


class FakeStack:
    def __init__(self):
        self.gatt_server = GATTServer()
        self.gap = FakeGap()
        self.local_address = "00:11:22:33:44:55"


async def test_gatt_server_registers_battery_and_hrs(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_gatt_server_main(stack, stop))
    asyncio.create_task(stopper())
    await task


async def test_gatt_server_starts_connectable_advertising_and_stops():
    stack = FakeStack()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    task = asyncio.create_task(_gatt_server_main(stack, stop))
    asyncio.create_task(stopper())
    await task

    advertiser = stack.gap.ble_advertiser
    assert len(advertiser.started) == 1
    config, ad_data, scan_rsp_data = advertiser.started[0]
    assert config.adv_type == 0x00
    assert ad_data.get_flags() == 0x06
    raw = ad_data.to_bytes()
    assert b"\x0f\x18" in raw
    assert b"\x0d\x18" in raw
    assert scan_rsp_data.get_complete_local_name() == "PyBlueHost GATT"
    assert advertiser.stopped is True
