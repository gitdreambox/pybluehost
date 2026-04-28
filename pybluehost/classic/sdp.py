"""SDP (Service Discovery Protocol) — data model, codec, server, and client."""
from __future__ import annotations

import struct
import asyncio
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from pybluehost.l2cap.channel import SimpleChannelEvents


# ---------------------------------------------------------------------------
# DataElement type and codec
# ---------------------------------------------------------------------------

class DataElementType(IntEnum):
    NIL = 0
    UINT = 1
    SINT = 2
    UUID = 3
    TEXT = 4
    BOOLEAN = 5
    SEQUENCE = 6
    ALTERNATIVE = 7
    URL = 8


@dataclass
class DataElement:
    type: DataElementType
    value: Any
    # Internal: size hint for encoding (number of bytes for UINT/SINT/UUID)
    _size_hint: int = 0

    # -- Constructors -------------------------------------------------------

    @classmethod
    def nil(cls) -> DataElement:
        return cls(type=DataElementType.NIL, value=None, _size_hint=0)

    @classmethod
    def uint8(cls, v: int) -> DataElement:
        return cls(type=DataElementType.UINT, value=v, _size_hint=1)

    @classmethod
    def uint16(cls, v: int) -> DataElement:
        return cls(type=DataElementType.UINT, value=v, _size_hint=2)

    @classmethod
    def uint32(cls, v: int) -> DataElement:
        return cls(type=DataElementType.UINT, value=v, _size_hint=4)

    @classmethod
    def uuid16(cls, v: int) -> DataElement:
        return cls(type=DataElementType.UUID, value=v, _size_hint=2)

    @classmethod
    def uuid128(cls, v: bytes) -> DataElement:
        return cls(type=DataElementType.UUID, value=v, _size_hint=16)

    @classmethod
    def text(cls, s: str) -> DataElement:
        return cls(type=DataElementType.TEXT, value=s)

    @classmethod
    def boolean(cls, v: bool) -> DataElement:
        return cls(type=DataElementType.BOOLEAN, value=v, _size_hint=1)

    @classmethod
    def sequence(cls, elements: list[DataElement]) -> DataElement:
        return cls(type=DataElementType.SEQUENCE, value=elements)

    @classmethod
    def alternative(cls, elements: list[DataElement]) -> DataElement:
        return cls(type=DataElementType.ALTERNATIVE, value=elements)

    @classmethod
    def url(cls, s: str) -> DataElement:
        return cls(type=DataElementType.URL, value=s)


# Size index mapping: size_index -> (fixed_size | None means variable with N-byte length prefix)
# 0: 1 byte, 1: 2 bytes, 2: 4 bytes, 3: 8 bytes, 4: 16 bytes
# 5: next 1 byte is length, 6: next 2 bytes, 7: next 4 bytes
_FIXED_SIZES = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16}
_VAR_LENGTH_BYTES = {5: 1, 6: 2, 7: 4}


def encode_data_element(de: DataElement) -> bytes:
    """Encode a DataElement to SDP wire format."""
    type_bits = de.type << 3

    if de.type == DataElementType.NIL:
        return bytes([type_bits | 0])

    if de.type in (DataElementType.UINT, DataElementType.SINT):
        size = de._size_hint
        fmt_map = {1: ">B", 2: ">H", 4: ">I", 8: ">Q"}
        size_idx_map = {1: 0, 2: 1, 4: 2, 8: 3}
        fmt = fmt_map[size]
        return bytes([type_bits | size_idx_map[size]]) + struct.pack(fmt, de.value)

    if de.type == DataElementType.UUID:
        size = de._size_hint
        if size == 2:
            return bytes([type_bits | 1]) + struct.pack(">H", de.value)
        if size == 4:
            return bytes([type_bits | 2]) + struct.pack(">I", de.value)
        if size == 16:
            return bytes([type_bits | 4]) + de.value
        raise ValueError(f"Invalid UUID size: {size}")

    if de.type == DataElementType.BOOLEAN:
        return bytes([type_bits | 0, 0x01 if de.value else 0x00])

    if de.type in (DataElementType.TEXT, DataElementType.URL):
        payload = de.value.encode("utf-8") if isinstance(de.value, str) else de.value
        return _encode_variable(type_bits, payload)

    if de.type in (DataElementType.SEQUENCE, DataElementType.ALTERNATIVE):
        payload = b"".join(encode_data_element(e) for e in de.value)
        return _encode_variable(type_bits, payload)

    raise ValueError(f"Unknown DataElement type: {de.type}")


def _encode_variable(type_bits: int, payload: bytes) -> bytes:
    """Encode a variable-length DataElement (TEXT, SEQUENCE, etc.)."""
    length = len(payload)
    if length < 256:
        return bytes([type_bits | 5, length]) + payload
    if length < 65536:
        return bytes([type_bits | 6]) + struct.pack(">H", length) + payload
    return bytes([type_bits | 7]) + struct.pack(">I", length) + payload


def decode_data_element(data: bytes, offset: int = 0) -> tuple[DataElement, int]:
    """Decode a DataElement from SDP wire format. Returns (element, bytes_consumed)."""
    header = data[offset]
    type_val = (header >> 3) & 0x1F
    size_idx = header & 0x07
    de_type = DataElementType(type_val)
    pos = offset + 1

    if de_type == DataElementType.NIL:
        return DataElement.nil(), 1

    # Fixed-size types (UINT, SINT, UUID, BOOLEAN)
    if size_idx in _FIXED_SIZES:
        size = _FIXED_SIZES[size_idx]
        payload = data[pos:pos + size]
        consumed = 1 + size

        if de_type == DataElementType.UINT:
            fmt_map = {1: ">B", 2: ">H", 4: ">I", 8: ">Q"}
            value = struct.unpack(fmt_map[size], payload)[0]
            return DataElement(type=de_type, value=value, _size_hint=size), consumed

        if de_type == DataElementType.SINT:
            fmt_map = {1: ">b", 2: ">h", 4: ">i", 8: ">q"}
            value = struct.unpack(fmt_map[size], payload)[0]
            return DataElement(type=de_type, value=value, _size_hint=size), consumed

        if de_type == DataElementType.UUID:
            if size == 2:
                value = struct.unpack(">H", payload)[0]
            elif size == 4:
                value = struct.unpack(">I", payload)[0]
            else:
                value = payload
            return DataElement(type=de_type, value=value, _size_hint=size), consumed

        if de_type == DataElementType.BOOLEAN:
            return DataElement.boolean(payload[0] != 0), consumed

    # Variable-length types
    if size_idx in _VAR_LENGTH_BYTES:
        len_bytes = _VAR_LENGTH_BYTES[size_idx]
        if len_bytes == 1:
            length = data[pos]
        elif len_bytes == 2:
            length = struct.unpack_from(">H", data, pos)[0]
        else:
            length = struct.unpack_from(">I", data, pos)[0]
        pos += len_bytes
        payload = data[pos:pos + length]
        consumed = 1 + len_bytes + length

        if de_type in (DataElementType.TEXT, DataElementType.URL):
            return DataElement(type=de_type, value=payload.decode("utf-8")), consumed

        if de_type in (DataElementType.SEQUENCE, DataElementType.ALTERNATIVE):
            elements: list[DataElement] = []
            inner_offset = 0
            while inner_offset < length:
                elem, elem_size = decode_data_element(payload, inner_offset)
                elements.append(elem)
                inner_offset += elem_size
            return DataElement(type=de_type, value=elements), consumed

    raise ValueError(f"Cannot decode DataElement: type={de_type}, size_idx={size_idx}")


# ---------------------------------------------------------------------------
# ServiceRecord
# ---------------------------------------------------------------------------

@dataclass
class ServiceRecord:
    """An SDP service record: a set of attribute ID → DataElement pairs."""
    handle: int = 0
    attributes: dict[int, DataElement] = field(default_factory=dict)


def make_rfcomm_service_record(
    service_uuid: int, channel: int, name: str,
) -> ServiceRecord:
    """Build a standard SDP record for an RFCOMM-based service (e.g. SPP)."""
    record = ServiceRecord()
    # 0x0001: ServiceClassIDList
    record.attributes[0x0001] = DataElement.sequence([
        DataElement.uuid16(service_uuid),
    ])
    # 0x0004: ProtocolDescriptorList
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([DataElement.uuid16(0x0100)]),  # L2CAP
        DataElement.sequence([
            DataElement.uuid16(0x0003),  # RFCOMM
            DataElement.uint8(channel),
        ]),
    ])
    # 0x0100: ServiceName
    record.attributes[0x0100] = DataElement.text(name)
    return record


# ---------------------------------------------------------------------------
# SDP PDU IDs
# ---------------------------------------------------------------------------

class _SDPPDU(IntEnum):
    ERROR_RESPONSE = 0x01
    SERVICE_SEARCH_REQUEST = 0x02
    SERVICE_SEARCH_RESPONSE = 0x03
    SERVICE_ATTRIBUTE_REQUEST = 0x04
    SERVICE_ATTRIBUTE_RESPONSE = 0x05
    SERVICE_SEARCH_ATTRIBUTE_REQUEST = 0x06
    SERVICE_SEARCH_ATTRIBUTE_RESPONSE = 0x07


# ---------------------------------------------------------------------------
# SDPServer
# ---------------------------------------------------------------------------

class SDPServer:
    """Local SDP server: register services, handle incoming PDU requests."""

    def __init__(self) -> None:
        self._records: dict[int, ServiceRecord] = {}
        self._next_handle = 0x00010000

    def register(self, record: ServiceRecord) -> int:
        """Register a service record. Returns assigned handle."""
        handle = self._next_handle
        self._next_handle += 1
        record.handle = handle
        self._records[handle] = record
        return handle

    def unregister(self, handle: int) -> None:
        """Remove a registered service record."""
        self._records.pop(handle, None)

    def handle_pdu(self, data: bytes) -> bytes:
        """Process an incoming SDP request PDU and return a response PDU."""
        pdu_id = data[0]
        txn_id = struct.unpack_from(">H", data, 1)[0]
        param_len = struct.unpack_from(">H", data, 3)[0]
        params = data[5:5 + param_len]

        if pdu_id == _SDPPDU.SERVICE_SEARCH_ATTRIBUTE_REQUEST:
            return self._handle_search_attribute(txn_id, params)

        # Unknown PDU → ErrorResponse
        return self._error_response(txn_id, 0x0003)  # Invalid Request Syntax

    def _handle_search_attribute(self, txn_id: int, params: bytes) -> bytes:
        """Handle ServiceSearchAttributeRequest."""
        offset = 0
        # Parse ServiceSearchPattern (sequence of UUIDs)
        search_pattern, consumed = decode_data_element(params, offset)
        offset += consumed
        # MaximumAttributeByteCount
        max_byte_count = struct.unpack_from(">H", params, offset)[0]
        offset += 2
        # AttributeIDList
        attr_id_list, consumed = decode_data_element(params, offset)
        offset += consumed
        # ContinuationState (ignored for simplicity)

        # Extract search UUIDs
        search_uuids = set()
        if search_pattern.type == DataElementType.SEQUENCE:
            for elem in search_pattern.value:
                if elem.type == DataElementType.UUID:
                    search_uuids.add(elem.value)

        # Extract requested attribute ID ranges
        attr_ranges = self._parse_attr_id_list(attr_id_list)

        # Search matching records
        matching = []
        for record in self._records.values():
            if self._record_matches(record, search_uuids):
                matching.append(record)

        # Build response: list of attribute lists
        attr_lists = []
        for record in matching:
            attrs = []
            for attr_id, de in sorted(record.attributes.items()):
                if self._attr_in_ranges(attr_id, attr_ranges):
                    attrs.append(DataElement.uint16(attr_id))
                    attrs.append(de)
            if attrs:
                attr_lists.append(DataElement.sequence(attrs))

        response_de = DataElement.sequence(attr_lists)
        response_bytes = encode_data_element(response_de)

        # Truncate to max_byte_count
        if len(response_bytes) > max_byte_count:
            response_bytes = response_bytes[:max_byte_count]

        # Build response PDU
        byte_count = struct.pack(">H", len(response_bytes))
        continuation = b"\x00"  # no continuation
        resp_params = byte_count + response_bytes + continuation
        return (
            bytes([_SDPPDU.SERVICE_SEARCH_ATTRIBUTE_RESPONSE])
            + struct.pack(">HH", txn_id, len(resp_params))
            + resp_params
        )

    def _record_matches(self, record: ServiceRecord, uuids: set) -> bool:
        """Check if a record contains any of the search UUIDs."""
        for de in record.attributes.values():
            if self._element_contains_uuid(de, uuids):
                return True
        return False

    def _element_contains_uuid(self, de: DataElement, uuids: set) -> bool:
        if de.type == DataElementType.UUID and de.value in uuids:
            return True
        if de.type in (DataElementType.SEQUENCE, DataElementType.ALTERNATIVE):
            for child in de.value:
                if self._element_contains_uuid(child, uuids):
                    return True
        return False

    def _parse_attr_id_list(self, de: DataElement) -> list[tuple[int, int]]:
        """Parse AttributeIDList into ranges of (start, end) inclusive."""
        ranges = []
        if de.type != DataElementType.SEQUENCE:
            return [(0, 0xFFFF)]
        for elem in de.value:
            if elem.type == DataElementType.UINT:
                if elem._size_hint == 4:
                    # Range: high 16 bits = start, low 16 bits = end
                    start = (elem.value >> 16) & 0xFFFF
                    end = elem.value & 0xFFFF
                    ranges.append((start, end))
                else:
                    # Single attribute ID
                    ranges.append((elem.value, elem.value))
        return ranges if ranges else [(0, 0xFFFF)]

    def _attr_in_ranges(self, attr_id: int, ranges: list[tuple[int, int]]) -> bool:
        return any(start <= attr_id <= end for start, end in ranges)

    def _error_response(self, txn_id: int, error_code: int) -> bytes:
        params = struct.pack(">H", error_code)
        return (
            bytes([_SDPPDU.ERROR_RESPONSE])
            + struct.pack(">HH", txn_id, len(params))
            + params
        )


# ---------------------------------------------------------------------------
# SDPClient
# ---------------------------------------------------------------------------

class SDPClient:
    """SDP client for querying remote SDP servers."""

    def __init__(self, l2cap: object | None = None) -> None:
        self._l2cap = l2cap
        self._txn_id = 1
        self._pending: dict[int, asyncio.Future[bytes]] = {}
        if l2cap is not None and hasattr(l2cap, "set_events"):
            l2cap.set_events(SimpleChannelEvents(on_data=self._on_pdu))

    async def _on_pdu(self, data: bytes) -> None:
        if len(data) < 5:
            return
        txn_id = struct.unpack_from(">H", data, 1)[0]
        future = self._pending.pop(txn_id, None)
        if future is not None and not future.done():
            future.set_result(data)

    def _next_txn_id(self) -> int:
        txn_id = self._txn_id
        self._txn_id += 1
        if self._txn_id > 0xFFFF:
            self._txn_id = 1
        return txn_id

    def _build_attr_id_list(
        self,
        attr_ids: list[int | tuple[int, int]] | None,
    ) -> DataElement:
        if attr_ids is None:
            return DataElement.sequence([DataElement.uint32(0x0000FFFF)])
        elements = []
        for attr in attr_ids:
            if isinstance(attr, tuple):
                elements.append(DataElement.uint32(((attr[0] & 0xFFFF) << 16) | (attr[1] & 0xFFFF)))
            else:
                elements.append(DataElement.uint16(attr))
        return DataElement.sequence(elements)

    async def _request(self, pdu_id: _SDPPDU, params: bytes) -> bytes:
        if self._l2cap is None or not hasattr(self._l2cap, "send"):
            raise NotImplementedError("Requires L2CAP connection")
        txn_id = self._next_txn_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending[txn_id] = future
        pdu = bytes([pdu_id]) + struct.pack(">HH", txn_id, len(params)) + params
        await self._l2cap.send(pdu)
        return await asyncio.wait_for(future, timeout=5.0)

    async def search(self, target: object, uuid: int) -> list[int]:
        """Send ServiceSearchRequest; return list of service record handles."""
        # Requires L2CAP connection to target on PSM 0x0001
        raise NotImplementedError("Requires L2CAP connection")

    async def get_attributes(
        self, target: object, handle: int, attr_ids: list[int],
    ) -> dict[int, DataElement]:
        """Send ServiceAttributeRequest for a specific handle."""
        raise NotImplementedError("Requires L2CAP connection")

    async def search_attributes(
        self, target: object, uuid: int,
        attr_ids: list[int | tuple[int, int]] | None = None,
    ) -> list[dict[int, DataElement]]:
        """Send ServiceSearchAttributeRequest (combined search + attributes)."""
        del target
        search_pattern = encode_data_element(
            DataElement.sequence([DataElement.uuid16(uuid)])
        )
        attr_id_list = encode_data_element(self._build_attr_id_list(attr_ids))
        params = search_pattern + struct.pack(">H", 0xFFFF) + attr_id_list + b"\x00"
        response = await self._request(_SDPPDU.SERVICE_SEARCH_ATTRIBUTE_REQUEST, params)
        if response[0] != _SDPPDU.SERVICE_SEARCH_ATTRIBUTE_RESPONSE:
            return []
        param_len = struct.unpack_from(">H", response, 3)[0]
        params = response[5:5 + param_len]
        if len(params) < 3:
            return []
        attr_byte_count = struct.unpack_from(">H", params)[0]
        attr_bytes = params[2:2 + attr_byte_count]
        if not attr_bytes:
            return []
        attr_lists_de, _consumed = decode_data_element(attr_bytes)
        records: list[dict[int, DataElement]] = []
        if attr_lists_de.type != DataElementType.SEQUENCE:
            return records
        for attr_list in attr_lists_de.value:
            if attr_list.type != DataElementType.SEQUENCE:
                continue
            record: dict[int, DataElement] = {}
            values = attr_list.value
            for i in range(0, len(values) - 1, 2):
                attr_id_de = values[i]
                attr_value_de = values[i + 1]
                if attr_id_de.type == DataElementType.UINT:
                    record[attr_id_de.value] = attr_value_de
            records.append(record)
        return records

    async def find_rfcomm_channel(
        self, target: object, service_uuid: int,
    ) -> int | None:
        """Convenience: find RFCOMM channel number for a given service UUID."""
        records = await self.search_attributes(
            target=target,
            uuid=service_uuid,
            attr_ids=[0x0004],
        )
        for record in records:
            protocol_list = record.get(0x0004)
            channel = self._find_rfcomm_channel_in_protocol_list(protocol_list)
            if channel is not None:
                return channel
        return None

    def _find_rfcomm_channel_in_protocol_list(self, de: DataElement | None) -> int | None:
        if de is None or de.type != DataElementType.SEQUENCE:
            return None
        for proto in de.value:
            if proto.type != DataElementType.SEQUENCE or not proto.value:
                continue
            first = proto.value[0]
            if first.type == DataElementType.UUID and first.value == 0x0003:
                if len(proto.value) >= 2 and proto.value[1].type == DataElementType.UINT:
                    return proto.value[1].value
        return None
