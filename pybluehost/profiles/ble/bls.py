"""Blood Pressure Service (0x1810)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_indicate, on_notify, on_read


class BloodPressureServer(BLEProfileServer):
    service_uuid = UUID16(0x1810)

    def __init__(self, feature: int = 0x0000) -> None:
        self._feature = feature

    @on_indicate(UUID16(0x2A35))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])

    @on_notify(UUID16(0x2A36))
    async def intermediate_cuff_pressure(self) -> bytes:
        return bytes([0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A49))
    async def read_feature(self) -> bytes:
        return self._feature.to_bytes(2, "little")
