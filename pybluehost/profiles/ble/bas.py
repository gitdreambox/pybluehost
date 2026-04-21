"""Battery Service (0x180F)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileClient, BLEProfileServer
from pybluehost.profiles.ble.decorators import on_notify, on_read


class BatteryServer(BLEProfileServer):
    service_uuid = UUID16(0x180F)

    def __init__(self, initial_level: int = 100) -> None:
        self._level = initial_level

    @on_read(UUID16(0x2A19))
    async def read_level(self) -> bytes:
        return bytes([self._level])

    @on_notify(UUID16(0x2A19))
    async def notify_level(self) -> bytes:
        return bytes([self._level])

    async def update_level(self, level: int) -> None:
        self._level = level


class BatteryClient(BLEProfileClient):
    service_uuid = UUID16(0x180F)

    async def read_battery_level(self) -> int:
        data = await self.read(UUID16(0x2A19))
        return data[0]
