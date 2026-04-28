import asyncio
from pybluehost.cli.app.spp_echo import _spp_echo_main


async def test_spp_echo_runs_on_stack_rfcomm_listener(stack):
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.01)
        stop.set()

    task = asyncio.create_task(_spp_echo_main(stack, stop))
    asyncio.create_task(stopper())
    await task


async def test_spp_echo_registers_sdp_record_and_rfcomm_listener():
    class FakeClassicDiscoverability:
        def __init__(self):
            self.device_names = []
            self.discoverable = []
            self.connectable = []

        async def set_device_name(self, name):
            self.device_names.append(name)

        async def set_discoverable(self, enabled):
            self.discoverable.append(enabled)

        async def set_connectable(self, enabled):
            self.connectable.append(enabled)

    class FakeGAP:
        def __init__(self):
            self.classic_discoverability = FakeClassicDiscoverability()

    class FakeRFCOMM:
        def __init__(self):
            self.listen_calls = []

        async def listen(self, server_channel, handler):
            self.listen_calls.append((server_channel, handler))

    class FakeStack:
        def __init__(self):
            from pybluehost.classic.sdp import SDPServer

            self.rfcomm = FakeRFCOMM()
            self.sdp = SDPServer()
            self.gap = FakeGAP()
            self.local_address = "00:11:22:33:44:55"

    stack = FakeStack()
    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.01)
        stop.set()

    task = asyncio.create_task(_spp_echo_main(stack, stop))
    asyncio.create_task(stopper())
    await task

    assert stack.rfcomm.listen_calls[0][0] == 1
    assert len(stack.sdp._records) == 1
    assert stack.gap.classic_discoverability.device_names == ["PyBlueHost SPP Echo"]
    assert stack.gap.classic_discoverability.discoverable == [True, False]
    assert stack.gap.classic_discoverability.connectable == [True, False]
