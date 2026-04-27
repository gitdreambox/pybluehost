import pytest
from pybluehost.cli._virtual_peer import virtual_peer_with
from pybluehost.profiles.ble import BatteryServer


async def test_virtual_peer_yields_powered_stack():
    async def factory(gatt):
        srv = BatteryServer(initial_level=42)
        await srv.register(gatt)

    async with virtual_peer_with(factory) as peer:
        assert peer.is_powered
        assert peer.local_address is not None


async def test_virtual_peer_closes_on_exit():
    async def factory(gatt):
        return

    async with virtual_peer_with(factory) as peer:
        pass
    assert not peer.is_powered
