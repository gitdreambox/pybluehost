import asyncio
from pybluehost.cli.app.spp_echo import _spp_echo_main


async def test_spp_echo_registers_sdp_record_and_rfcomm_listener():
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
