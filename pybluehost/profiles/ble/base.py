"""BLE Profile base classes — BLEProfileServer and BLEProfileClient."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pybluehost.ble.gatt import GATTClient, GATTServer, ServiceHandles
    from pybluehost.core.uuid import UUID16, UUID128


class BLEProfileServer(ABC):
    """Base class for BLE profile server implementations.

    Subclasses set ``service_uuid`` and decorate methods with
    ``@on_read``, ``@on_write``, ``@on_notify``, ``@on_indicate``.
    Calling ``register(gatt_server)`` builds a ServiceDefinition from
    the decorated methods and adds it to the GATT server.
    """

    service_uuid: UUID16 | UUID128

    async def register(self, gatt_server: GATTServer) -> ServiceHandles:
        """Register the service and bind decorated callbacks into the GATT DB."""
        svc_def = self._build_service_definition()
        handles = gatt_server.add_service(svc_def)

        # Bind read callbacks: store initial value from callback
        for name in dir(self.__class__):
            method = getattr(self.__class__, name, None)
            if method is None:
                continue
            if hasattr(method, "_att_read"):
                uuid = method._att_read
                handle = gatt_server.find_characteristic_value_handle(uuid)
                if handle is not None:
                    bound = getattr(self, name)
                    value = await bound()
                    gatt_server.db.write(handle, value)

        return handles

    def _build_service_definition(self):
        """Introspect decorated methods and build a ServiceDefinition."""
        from pybluehost.ble.gatt import (
            CharProperties,
            CharacteristicDefinition,
            Permissions,
            ServiceDefinition,
        )

        seen: dict = {}  # uuid -> CharProperties
        for name in dir(self.__class__):
            method = getattr(self.__class__, name, None)
            if method is None:
                continue
            for attr, prop in [
                ("_att_read", CharProperties.READ),
                ("_att_write", CharProperties.WRITE),
                ("_att_notify", CharProperties.NOTIFY),
                ("_att_indicate", CharProperties.INDICATE),
            ]:
                if hasattr(method, attr):
                    uuid = getattr(method, attr)
                    if uuid not in seen:
                        seen[uuid] = CharProperties(0)
                    seen[uuid] |= prop

        chars = [
            CharacteristicDefinition(
                uuid=uuid,
                properties=props,
                permissions=Permissions.READABLE | Permissions.WRITABLE,
            )
            for uuid, props in seen.items()
        ]
        return ServiceDefinition(uuid=self.service_uuid, characteristics=chars)


class BLEProfileClient(ABC):
    """Base class for BLE profile client implementations.

    Subclasses set ``service_uuid`` and call ``discover(gatt_client)``
    to locate the service and cache characteristic handles.
    """

    service_uuid: UUID16 | UUID128

    def __init__(self) -> None:
        self._gatt: GATTClient | None = None
        self._char_handles: dict = {}

    async def discover(self, gatt_client: GATTClient) -> None:
        """Discover the profile service and cache characteristic handles."""
        self._gatt = gatt_client
        services = await gatt_client.discover_all_services()
        service = next(
            (s for s in services if s.uuid == self.service_uuid), None
        )
        if service is None:
            raise ValueError(f"Service {self.service_uuid} not found")
        chars = await gatt_client.discover_characteristics(service)
        self._char_handles = {c.uuid: c for c in chars}

    async def read(self, uuid: UUID16 | UUID128) -> bytes:
        """Read a characteristic by UUID."""
        char = self._char_handles[uuid]
        return await self._gatt.read_characteristic(char)

    async def write(self, uuid: UUID16 | UUID128, value: bytes) -> None:
        """Write a characteristic by UUID."""
        char = self._char_handles[uuid]
        await self._gatt.write_characteristic(char, value)
