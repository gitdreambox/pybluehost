"""Cycling Speed and Cadence Service (0x1816)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_notify, on_read


class CSCServer(BLEProfileServer):
    service_uuid = UUID16(0x1816)

    @on_notify(UUID16(0x2A5B))
    async def measurement(self) -> bytes:
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00])

    @on_read(UUID16(0x2A5C))
    async def read_feature(self) -> bytes:
        return bytes([0x00, 0x00])
