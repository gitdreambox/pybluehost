"""Running Speed and Cadence Service (0x1814)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_notify, on_read


class RSCServer(BLEProfileServer):
    service_uuid = UUID16(0x1814)

    @on_notify(UUID16(0x2A53))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A54))
    async def read_feature(self) -> bytes:
        return bytes([0x00, 0x00])
