"""Human Interface Device Service (0x1812)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileServer
from pybluehost.profiles.ble.decorators import on_notify, on_read, on_write


class HIDServer(BLEProfileServer):
    service_uuid = UUID16(0x1812)

    def __init__(
        self,
        hid_info: bytes = bytes([0x11, 0x01, 0x00, 0x00]),
        report_map: bytes = b"",
    ) -> None:
        self._hid_info = hid_info
        self._report_map = report_map

    @on_read(UUID16(0x2A4A))
    async def read_hid_info(self) -> bytes:
        return self._hid_info

    @on_read(UUID16(0x2A4B))
    async def read_report_map(self) -> bytes:
        return self._report_map

    @on_notify(UUID16(0x2A4D))
    async def input_report(self) -> bytes:
        return b"\x00"

    @on_write(UUID16(0x2A4C))
    async def control_point(self, value: bytes) -> None:
        pass
