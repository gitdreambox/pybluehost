"""Device Information Service (0x180A)."""
from __future__ import annotations

from pybluehost.core.uuid import UUID16
from pybluehost.profiles.ble.base import BLEProfileClient, BLEProfileServer
from pybluehost.profiles.ble.decorators import on_read


class DeviceInformationServer(BLEProfileServer):
    service_uuid = UUID16(0x180A)

    def __init__(
        self,
        manufacturer: str = "",
        model: str = "",
        hardware_rev: str = "",
        firmware_rev: str = "",
        software_rev: str = "",
    ) -> None:
        self._manufacturer = manufacturer
        self._model = model
        self._hardware_rev = hardware_rev
        self._firmware_rev = firmware_rev
        self._software_rev = software_rev

    @on_read(UUID16(0x2A29))
    async def read_manufacturer(self) -> bytes:
        return self._manufacturer.encode()

    @on_read(UUID16(0x2A24))
    async def read_model(self) -> bytes:
        return self._model.encode()

    @on_read(UUID16(0x2A27))
    async def read_hardware_rev(self) -> bytes:
        return self._hardware_rev.encode()

    @on_read(UUID16(0x2A26))
    async def read_firmware_rev(self) -> bytes:
        return self._firmware_rev.encode()

    @on_read(UUID16(0x2A28))
    async def read_software_rev(self) -> bytes:
        return self._software_rev.encode()


class DeviceInformationClient(BLEProfileClient):
    service_uuid = UUID16(0x180A)

    async def read_manufacturer(self) -> str:
        return (await self.read(UUID16(0x2A29))).decode()

    async def read_model(self) -> str:
        return (await self.read(UUID16(0x2A24))).decode()
