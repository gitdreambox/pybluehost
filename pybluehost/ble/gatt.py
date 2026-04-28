"""GATT Server and Client — attribute database, service definitions, request handling."""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from enum import IntFlag
from typing import Awaitable, Callable

from pybluehost.core.uuid import UUID16, UUID128
from pybluehost.ble.att import (
    ATTOpcode, ATTPdu, ATTBearer, ATTError,
    ATT_Error_Response,
    ATT_Exchange_MTU_Request, ATT_Exchange_MTU_Response,
    ATT_Read_Request, ATT_Read_Response,
    ATT_Write_Request, ATT_Write_Response,
    ATT_Read_By_Type_Request, ATT_Read_By_Type_Response,
    ATT_Read_By_Group_Type_Request, ATT_Read_By_Group_Type_Response,
    ATT_Find_Information_Request, ATT_Find_Information_Response,
    ATT_Handle_Value_Notification, ATT_Handle_Value_Indication,
    decode_att_pdu,
)


# GATT UUIDs
UUID_PRIMARY_SERVICE = UUID16(0x2800)
UUID_SECONDARY_SERVICE = UUID16(0x2801)
UUID_CHARACTERISTIC = UUID16(0x2803)
UUID_CCCD = UUID16(0x2902)  # Client Characteristic Configuration Descriptor
UUID_SERVICE_CHANGED = UUID16(0x2A05)


class Permissions(IntFlag):
    READABLE = 0x01
    WRITABLE = 0x02
    READABLE_ENCRYPTED = 0x04
    WRITABLE_ENCRYPTED = 0x08


class CharProperties(IntFlag):
    BROADCAST = 0x01
    READ = 0x02
    WRITE_WITHOUT_RESPONSE = 0x04
    WRITE = 0x08
    NOTIFY = 0x10
    INDICATE = 0x20
    AUTHENTICATED_SIGNED_WRITES = 0x40
    EXTENDED_PROPERTIES = 0x80


@dataclass
class Attribute:
    handle: int
    type_uuid: UUID16 | UUID128
    permissions: Permissions
    value: bytes = b""


class AttributeDatabase:
    """Linear attribute database with auto-incrementing handles."""

    def __init__(self) -> None:
        self._attrs: list[Attribute] = []
        self._next_handle: int = 0x0001

    def add(self, type_uuid: UUID16 | UUID128, permissions: Permissions, value: bytes = b"") -> int:
        handle = self._next_handle
        self._next_handle += 1
        self._attrs.append(Attribute(handle=handle, type_uuid=type_uuid, permissions=permissions, value=value))
        return handle

    def read(self, handle: int) -> bytes:
        for attr in self._attrs:
            if attr.handle == handle:
                return attr.value
        raise KeyError(f"No attribute with handle 0x{handle:04X}")

    def write(self, handle: int, value: bytes) -> None:
        for attr in self._attrs:
            if attr.handle == handle:
                attr.value = value
                return
        raise KeyError(f"No attribute with handle 0x{handle:04X}")

    def get(self, handle: int) -> Attribute | None:
        for attr in self._attrs:
            if attr.handle == handle:
                return attr
        return None

    def find_by_type_in_range(self, start: int, end: int, type_uuid: UUID16 | UUID128) -> list[Attribute]:
        """Find attributes by type UUID within a handle range."""
        type_bytes = type_uuid.to_bytes()
        return [a for a in self._attrs
                if start <= a.handle <= end and a.type_uuid.to_bytes() == type_bytes]

    def find_by_group_type(self, start: int, end: int, type_uuid: UUID16 | UUID128) -> list[tuple[int, int, bytes]]:
        """Find service groups. Returns list of (start_handle, end_handle, uuid_value)."""
        type_bytes = type_uuid.to_bytes()
        groups = []
        for i, attr in enumerate(self._attrs):
            if start <= attr.handle <= end and attr.type_uuid.to_bytes() == type_bytes:
                # Find end of this group (next service declaration - 1, or last handle)
                end_handle = self._attrs[-1].handle  # default: last attr
                for j in range(i + 1, len(self._attrs)):
                    if self._attrs[j].type_uuid.to_bytes() == type_bytes:
                        end_handle = self._attrs[j].handle - 1
                        break
                groups.append((attr.handle, end_handle, attr.value))
        return groups

    @property
    def last_handle(self) -> int:
        return self._next_handle - 1 if self._attrs else 0


# Service/Characteristic definition dataclasses

@dataclass
class DescriptorDefinition:
    uuid: UUID16 | UUID128
    permissions: Permissions
    value: bytes = b""


@dataclass
class CharacteristicDefinition:
    uuid: UUID16 | UUID128
    properties: CharProperties
    permissions: Permissions
    value: bytes = b""
    descriptors: list[DescriptorDefinition] = field(default_factory=list)


@dataclass
class ServiceDefinition:
    uuid: UUID16 | UUID128
    characteristics: list[CharacteristicDefinition] = field(default_factory=list)
    is_primary: bool = True


# Handle info returned after adding a service

@dataclass
class CharacteristicHandles:
    declaration_handle: int
    value_handle: int
    cccd_handle: int | None = None
    descriptor_handles: list[int] = field(default_factory=list)


@dataclass
class ServiceHandles:
    service_handle: int
    end_handle: int
    characteristic_handles: list[CharacteristicHandles] = field(default_factory=list)


@dataclass
class DiscoveredCharacteristic:
    declaration_handle: int
    value_handle: int
    properties: int
    uuid: bytes


@dataclass
class DiscoveredDescriptor:
    handle: int
    uuid: bytes


class GATTServer:
    """GATT Server: manages attribute database and handles ATT requests."""

    def __init__(self) -> None:
        self.db = AttributeDatabase()
        self._notification_callback: Callable | None = None
        self._read_handlers: dict[int, Callable[[], bytes | Awaitable[bytes]]] = {}
        self._write_handlers: dict[int, Callable[[bytes], object | Awaitable[object]]] = {}
        # conn_handle -> set of value_handles with notifications enabled
        self._notifications_enabled: dict[int, set[int]] = {}

    def add_service(self, svc: ServiceDefinition) -> ServiceHandles:
        """Add a service to the attribute database, returning handle info."""
        svc_uuid = UUID_PRIMARY_SERVICE if svc.is_primary else UUID_SECONDARY_SERVICE
        svc_value = svc.uuid.to_bytes()
        svc_handle = self.db.add(type_uuid=svc_uuid, permissions=Permissions.READABLE, value=svc_value)

        char_handles_list = []
        for char_def in svc.characteristics:
            # Characteristic Declaration (0x2803)
            # Value: properties(1) + value_handle(2 LE) + uuid(2 or 16)
            value_handle_placeholder = self.db._next_handle + 1
            char_decl_value = struct.pack("<BH", int(char_def.properties), value_handle_placeholder) + char_def.uuid.to_bytes()
            decl_handle = self.db.add(type_uuid=UUID_CHARACTERISTIC, permissions=Permissions.READABLE, value=char_decl_value)

            # Characteristic Value
            value_handle = self.db.add(type_uuid=char_def.uuid, permissions=char_def.permissions, value=char_def.value)

            # CCCD if NOTIFY or INDICATE
            cccd_handle = None
            if char_def.properties & (CharProperties.NOTIFY | CharProperties.INDICATE):
                cccd_handle = self.db.add(
                    type_uuid=UUID_CCCD,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00\x00",
                )

            # Additional descriptors
            desc_handles = []
            for desc in char_def.descriptors:
                dh = self.db.add(type_uuid=desc.uuid, permissions=desc.permissions, value=desc.value)
                desc_handles.append(dh)

            char_handles_list.append(CharacteristicHandles(
                declaration_handle=decl_handle,
                value_handle=value_handle,
                cccd_handle=cccd_handle,
                descriptor_handles=desc_handles,
            ))

        return ServiceHandles(
            service_handle=svc_handle,
            end_handle=self.db.last_handle,
            characteristic_handles=char_handles_list,
        )

    async def handle_request(self, conn_handle: int, pdu: ATTPdu) -> ATTPdu:
        """Handle an incoming ATT request, return the response PDU."""
        if isinstance(pdu, ATT_Read_Request):
            return await self._handle_read(pdu)
        elif isinstance(pdu, ATT_Write_Request):
            return await self._handle_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Exchange_MTU_Request):
            return ATT_Exchange_MTU_Response(server_rx_mtu=512)
        elif isinstance(pdu, ATT_Read_By_Group_Type_Request):
            return self._handle_read_by_group_type(pdu)
        elif isinstance(pdu, ATT_Read_By_Type_Request):
            return self._handle_read_by_type(pdu)
        elif isinstance(pdu, ATT_Find_Information_Request):
            return self._handle_find_information(pdu)
        return ATT_Error_Response(
            request_opcode_in_error=0, attribute_handle_in_error=0,
            error_code=0x06,  # Request Not Supported
        )

    async def _handle_read(self, pdu: ATT_Read_Request) -> ATTPdu:
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=0x0A,  # Attribute Not Found
            )
        if not (attr.permissions & Permissions.READABLE):
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=0x02,  # Read Not Permitted
            )
        handler = self._read_handlers.get(pdu.attribute_handle)
        if handler is not None:
            value = handler()
            if asyncio.iscoroutine(value):
                value = await value
            attr.value = value
        return ATT_Read_Response(attribute_value=attr.value)

    async def _handle_write(self, conn_handle: int, pdu: ATT_Write_Request) -> ATTPdu:
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=0x0A,
            )
        if not (attr.permissions & Permissions.WRITABLE):
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=0x03,  # Write Not Permitted
            )
        # Check if this is a CCCD write
        if attr.type_uuid.to_bytes() == UUID_CCCD.to_bytes() and len(pdu.attribute_value) >= 2:
            cccd_val = struct.unpack_from("<H", pdu.attribute_value)[0]
            # Find the value handle (CCCD is always after the value handle)
            value_handle = pdu.attribute_handle - 1
            if cccd_val & 0x0001:  # notifications enabled
                self.enable_notifications(conn_handle, value_handle)
            else:
                self.disable_notifications(conn_handle, value_handle)
        attr.value = pdu.attribute_value
        handler = self._write_handlers.get(pdu.attribute_handle)
        if handler is not None:
            result = handler(pdu.attribute_value)
            if asyncio.iscoroutine(result):
                await result
        return ATT_Write_Response()

    def _handle_read_by_group_type(self, pdu: ATT_Read_By_Group_Type_Request) -> ATTPdu:
        groups = self.db.find_by_group_type(
            pdu.starting_handle, pdu.ending_handle,
            UUID16.from_bytes(pdu.attribute_group_type) if len(pdu.attribute_group_type) == 2 else UUID128.from_bytes(pdu.attribute_group_type),
        )
        if not groups:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BY_GROUP_TYPE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,
            )
        # Each entry: start_handle(2) + end_handle(2) + value
        entry_len = 4 + len(groups[0][2])
        data = b""
        for start, end, value in groups:
            if len(value) + 4 != entry_len:
                break
            data += struct.pack("<HH", start, end) + value
        return ATT_Read_By_Group_Type_Response(length=entry_len, attribute_data_list=data)

    def _handle_read_by_type(self, pdu: ATT_Read_By_Type_Request) -> ATTPdu:
        uuid = UUID16.from_bytes(pdu.attribute_type) if len(pdu.attribute_type) == 2 else UUID128.from_bytes(pdu.attribute_type)
        attrs = self.db.find_by_type_in_range(pdu.starting_handle, pdu.ending_handle, uuid)
        if not attrs:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BY_TYPE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,
            )
        entry_len = 2 + len(attrs[0].value)
        data = b""
        for attr in attrs:
            if len(attr.value) + 2 != entry_len:
                break
            data += struct.pack("<H", attr.handle) + attr.value
        return ATT_Read_By_Type_Response(length=entry_len, attribute_data_list=data)

    def _handle_find_information(self, pdu: ATT_Find_Information_Request) -> ATTPdu:
        results = []
        for attr in self.db._attrs:
            if pdu.starting_handle <= attr.handle <= pdu.ending_handle:
                results.append(attr)
        if not results:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.FIND_INFORMATION_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,
            )
        # Determine format based on first result
        first_uuid_bytes = results[0].type_uuid.to_bytes()
        fmt = 0x01 if len(first_uuid_bytes) == 2 else 0x02
        data = b""
        for attr in results:
            uuid_bytes = attr.type_uuid.to_bytes()
            if len(uuid_bytes) != (2 if fmt == 0x01 else 16):
                break
            data += struct.pack("<H", attr.handle) + uuid_bytes
        return ATT_Find_Information_Response(format=fmt, information_data=data)

    # Notification/Indication API

    def enable_notifications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle not in self._notifications_enabled:
            self._notifications_enabled[conn_handle] = set()
        self._notifications_enabled[conn_handle].add(value_handle)

    def disable_notifications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle in self._notifications_enabled:
            self._notifications_enabled[conn_handle].discard(value_handle)

    def on_notification_sent(self, handler: Callable) -> None:
        self._notification_callback = handler

    def register_read_handler(
        self,
        handle: int,
        handler: Callable[[], bytes | Awaitable[bytes]],
    ) -> None:
        self._read_handlers[handle] = handler

    def register_write_handler(
        self,
        handle: int,
        handler: Callable[[bytes], object | Awaitable[object]],
    ) -> None:
        self._write_handlers[handle] = handler

    async def notify(self, handle: int, value: bytes, connections: list[int] | None = None) -> None:
        """Send a notification to all subscribed connections (or specified ones)."""
        targets = connections or list(self._notifications_enabled.keys())
        for conn in targets:
            enabled = self._notifications_enabled.get(conn, set())
            if handle in enabled:
                if self._notification_callback:
                    result = self._notification_callback(handle, value, conn)
                    if asyncio.iscoroutine(result):
                        await result

    async def indicate(self, handle: int, value: bytes, connection: int) -> None:
        """Send an indication (requires confirmation from client)."""
        if self._notification_callback:
            result = self._notification_callback(handle, value, connection)
            if asyncio.iscoroutine(result):
                await result

    def find_characteristic_value_handle(self, uuid: UUID16 | UUID128) -> int | None:
        uuid_bytes = uuid.to_bytes()
        for attr in self.db._attrs:
            if attr.type_uuid.to_bytes() == uuid_bytes and attr.type_uuid.to_bytes() != UUID_CHARACTERISTIC.to_bytes():
                return attr.handle
        return None


class GATTClient:
    """GATT Client — wraps ATTBearer for service discovery and attribute access."""

    def __init__(self, bearer: ATTBearer) -> None:
        self._bearer = bearer

    async def discover_all_services(self) -> list[tuple[int, int, bytes]]:
        """Discover all primary services via Read_By_Group_Type."""
        services: list[tuple[int, int, bytes]] = []
        start = 0x0001
        while start <= 0xFFFF:
            req = ATT_Read_By_Group_Type_Request(
                starting_handle=start, ending_handle=0xFFFF,
                attribute_group_type=UUID_PRIMARY_SERVICE.to_bytes(),
            )
            resp = await self._bearer._request(req, ATTOpcode.READ_BY_GROUP_TYPE_RESPONSE)
            if isinstance(resp, ATT_Error_Response):
                break
            if isinstance(resp, ATT_Read_By_Group_Type_Response):
                entry_len = resp.length
                data = resp.attribute_data_list
                offset = 0
                while offset + entry_len <= len(data):
                    s_handle, e_handle = struct.unpack_from("<HH", data, offset)
                    uuid_val = data[offset + 4: offset + entry_len]
                    services.append((s_handle, e_handle, uuid_val))
                    start = e_handle + 1
                    offset += entry_len
                if start > 0xFFFF:
                    break
            else:
                break
        return services

    async def discover_characteristics(
        self, start_handle: int, end_handle: int
    ) -> list[DiscoveredCharacteristic]:
        """Discover characteristic declarations in a handle range."""
        characteristics: list[DiscoveredCharacteristic] = []
        start = start_handle
        while start <= end_handle:
            req = ATT_Read_By_Type_Request(
                starting_handle=start,
                ending_handle=end_handle,
                attribute_type=UUID_CHARACTERISTIC.to_bytes(),
            )
            resp = await self._bearer._request(req, ATTOpcode.READ_BY_TYPE_RESPONSE)
            if isinstance(resp, ATT_Error_Response):
                break
            if not isinstance(resp, ATT_Read_By_Type_Response):
                break
            entry_len = resp.length
            data = resp.attribute_data_list
            offset = 0
            last_decl_handle = 0
            while entry_len >= 7 and offset + entry_len <= len(data):
                decl_handle = struct.unpack_from("<H", data, offset)[0]
                value = data[offset + 2: offset + entry_len]
                if len(value) < 5:
                    break
                properties = value[0]
                value_handle = struct.unpack_from("<H", value, 1)[0]
                uuid = value[3:]
                if decl_handle >= start:
                    characteristics.append(
                        DiscoveredCharacteristic(
                            declaration_handle=decl_handle,
                            value_handle=value_handle,
                            properties=properties,
                            uuid=uuid,
                        )
                    )
                    last_decl_handle = decl_handle
                offset += entry_len
            if last_decl_handle == 0:
                break
            if last_decl_handle < start:
                break
            start = last_decl_handle + 1
        return characteristics

    async def discover_descriptors(
        self, start_handle: int, end_handle: int
    ) -> list[DiscoveredDescriptor]:
        """Discover attribute UUIDs in a descriptor/value handle range."""
        descriptors: list[DiscoveredDescriptor] = []
        if start_handle > end_handle:
            return descriptors
        start = start_handle
        while start <= end_handle:
            req = ATT_Find_Information_Request(
                starting_handle=start,
                ending_handle=end_handle,
            )
            resp = await self._bearer._request(req, ATTOpcode.FIND_INFORMATION_RESPONSE)
            if isinstance(resp, ATT_Error_Response):
                break
            if not isinstance(resp, ATT_Find_Information_Response):
                break
            entry_len = 4 if resp.format == 0x01 else 18 if resp.format == 0x02 else 0
            if entry_len == 0:
                break
            data = resp.information_data
            offset = 0
            last_handle = 0
            while offset + entry_len <= len(data):
                handle = struct.unpack_from("<H", data, offset)[0]
                uuid = data[offset + 2: offset + entry_len]
                if handle >= start:
                    descriptors.append(DiscoveredDescriptor(handle=handle, uuid=uuid))
                    last_handle = handle
                offset += entry_len
            if last_handle == 0:
                break
            if last_handle < start:
                break
            start = last_handle + 1
        return descriptors

    async def read_characteristic(self, handle: int) -> bytes:
        return await self._bearer.read(handle)

    async def write_characteristic(self, handle: int, value: bytes) -> None:
        await self._bearer.write(handle, value)
