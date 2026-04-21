"""GAP Service (0x1800) — Device Name and Appearance."""
from __future__ import annotations

import struct

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_read, on_write


class GAPServiceServer(BLEProfileServer):
    service_uuid = UUID16(0x1800)

    def __init__(self, device_name: str = "PyBlueHost", appearance: int = 0x0000) -> None:
        self._name = device_name
        self._appearance = appearance

    @on_read(UUID16(0x2A00))
    async def read_name(self) -> bytes:
        return self._name.encode()

    @on_write(UUID16(0x2A00))
    async def write_name(self, value: bytes) -> None:
        self._name = value.decode(errors="replace")

    @on_read(UUID16(0x2A01))
    async def read_appearance(self) -> bytes:
        return struct.pack("<H", self._appearance)
