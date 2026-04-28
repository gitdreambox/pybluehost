import asyncio
import itertools
from pybluehost.ble.gatt import GATTServer
from pybluehost.core.uuid import UUID16
from pybluehost.cli.app.hr_monitor import _hr_monitor_main


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


async def test_hr_monitor_pushes_measurements_until_stop(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.15)
        stop.set()

    task = asyncio.create_task(_hr_monitor_main(stack, stop, interval=0.05))
    asyncio.create_task(stopper())
    await task


async def test_hr_monitor_advertises_and_notifies_subscribed_connections(monkeypatch):
    stack = FakeStack()
    stop = asyncio.Event()
    notifications = []
    stack.gatt_server.on_notification_sent(
        lambda handle, value, conn: notifications.append((handle, value, conn))
    )
    values = itertools.cycle([80, 81, 82])
    monkeypatch.setattr("pybluehost.cli.app.hr_monitor.random.randint", lambda _a, _b: next(values))

    async def subscribe_and_stop():
        handle = None
        for _ in range(20):
            handle = stack.gatt_server.find_characteristic_value_handle(UUID16(0x2A37))
            if handle is not None:
                break
            await asyncio.sleep(0.01)
        assert handle is not None
        stack.gatt_server.enable_notifications(conn_handle=0x0040, value_handle=handle)
        await asyncio.sleep(0.08)
        stop.set()

    task = asyncio.create_task(_hr_monitor_main(stack, stop, interval=0.02))
    asyncio.create_task(subscribe_and_stop())
    await task

    advertiser = stack.gap.ble_advertiser
    assert len(advertiser.started) == 1
    config, ad_data, scan_rsp_data = advertiser.started[0]
    assert config.adv_type == 0x00
    assert b"\x0d\x18" in ad_data.to_bytes()
    assert scan_rsp_data.get_complete_local_name() == "PyBlueHost HR"
    assert advertiser.stopped is True
    assert notifications
    assert notifications[-1][1] in (bytes([0x00, 80]), bytes([0x00, 81]), bytes([0x00, 82]))
