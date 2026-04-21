"""Heart Rate Service (0x180D)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileClient, BLEProfileServer
from pybluehost.profiles.ble.decorators import on_notify, on_read, on_write


class HeartRateServer(BLEProfileServer):
    service_uuid = UUID16(0x180D)

    def __init__(self, sensor_location: int = 0x00) -> None:
        self._location = sensor_location
        self._last_bpm = 0

    @on_read(UUID16(0x2A38))
    async def read_location(self) -> bytes:
        return bytes([self._location])

    @on_notify(UUID16(0x2A37))
    async def notify_hrm(self) -> bytes:
        return bytes([0x00, self._last_bpm])

    @on_write(UUID16(0x2A39))
    async def write_control_point(self, value: bytes) -> None:
        pass

    async def update_measurement(self, bpm: int) -> None:
        self._last_bpm = bpm


class HeartRateClient(BLEProfileClient):
    service_uuid = UUID16(0x180D)

    async def read_sensor_location(self) -> int:
        data = await self.read(UUID16(0x2A38))
        return data[0]

    async def reset_energy_expended(self) -> None:
        await self.write(UUID16(0x2A39), b"\x01")
