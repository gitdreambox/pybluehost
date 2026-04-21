"""GATT Service (0x1801) — Service Changed indication."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_indicate


class GATTServiceServer(BLEProfileServer):
    service_uuid = UUID16(0x1801)

    @on_indicate(UUID16(0x2A05))
    async def service_changed(self) -> bytes:
        return bytes([0x01, 0x00, 0xFF, 0xFF])
