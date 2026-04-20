"""ATT Protocol Data Unit codec and ATTBearer.

Implements all standard ATT opcodes from BT Core Spec Vol 3 Part F,
PDU encode/decode for each, and an async ATTBearer for request/response
machinery over an L2CAP channel.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable


class ATTOpcode(IntEnum):
    ERROR_RESPONSE = 0x01
    EXCHANGE_MTU_REQUEST = 0x02
    EXCHANGE_MTU_RESPONSE = 0x03
    FIND_INFORMATION_REQUEST = 0x04
    FIND_INFORMATION_RESPONSE = 0x05
    FIND_BY_TYPE_VALUE_REQUEST = 0x06
    FIND_BY_TYPE_VALUE_RESPONSE = 0x07
    READ_BY_TYPE_REQUEST = 0x08
    READ_BY_TYPE_RESPONSE = 0x09
    READ_REQUEST = 0x0A
    READ_RESPONSE = 0x0B
    READ_BLOB_REQUEST = 0x0C
    READ_BLOB_RESPONSE = 0x0D
    READ_MULTIPLE_REQUEST = 0x0E
    READ_MULTIPLE_RESPONSE = 0x0F
    READ_BY_GROUP_TYPE_REQUEST = 0x10
    READ_BY_GROUP_TYPE_RESPONSE = 0x11
    WRITE_REQUEST = 0x12
    WRITE_RESPONSE = 0x13
    PREPARE_WRITE_REQUEST = 0x16
    PREPARE_WRITE_RESPONSE = 0x17
    EXECUTE_WRITE_REQUEST = 0x18
    EXECUTE_WRITE_RESPONSE = 0x19
    HANDLE_VALUE_NOTIFICATION = 0x1B
    HANDLE_VALUE_INDICATION = 0x1D
    HANDLE_VALUE_CONFIRMATION = 0x1E
    WRITE_COMMAND = 0x52
    SIGNED_WRITE_COMMAND = 0xD2


# ---------------------------------------------------------------------------
# PDU base
# ---------------------------------------------------------------------------

@dataclass
class ATTPdu:
    """Base class for all ATT PDUs."""

    def to_bytes(self) -> bytes:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete PDU classes
# ---------------------------------------------------------------------------

@dataclass
class ATT_Error_Response(ATTPdu):
    request_opcode_in_error: int = 0
    attribute_handle_in_error: int = 0
    error_code: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<BBHB",
            ATTOpcode.ERROR_RESPONSE,
            self.request_opcode_in_error,
            self.attribute_handle_in_error,
            self.error_code,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Error_Response:
        opcode_in_err, handle, err = struct.unpack_from("<BHB", data, 1)
        return cls(
            request_opcode_in_error=opcode_in_err,
            attribute_handle_in_error=handle,
            error_code=err,
        )


@dataclass
class ATT_Exchange_MTU_Request(ATTPdu):
    client_rx_mtu: int = 23

    def to_bytes(self) -> bytes:
        return struct.pack("<BH", ATTOpcode.EXCHANGE_MTU_REQUEST, self.client_rx_mtu)

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Exchange_MTU_Request:
        (mtu,) = struct.unpack_from("<H", data, 1)
        return cls(client_rx_mtu=mtu)


@dataclass
class ATT_Exchange_MTU_Response(ATTPdu):
    server_rx_mtu: int = 23

    def to_bytes(self) -> bytes:
        return struct.pack("<BH", ATTOpcode.EXCHANGE_MTU_RESPONSE, self.server_rx_mtu)

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Exchange_MTU_Response:
        (mtu,) = struct.unpack_from("<H", data, 1)
        return cls(server_rx_mtu=mtu)


@dataclass
class ATT_Find_Information_Request(ATTPdu):
    starting_handle: int = 0
    ending_handle: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<BHH",
            ATTOpcode.FIND_INFORMATION_REQUEST,
            self.starting_handle,
            self.ending_handle,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Find_Information_Request:
        start, end = struct.unpack_from("<HH", data, 1)
        return cls(starting_handle=start, ending_handle=end)


@dataclass
class ATT_Find_Information_Response(ATTPdu):
    format: int = 0
    information_data: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BB", ATTOpcode.FIND_INFORMATION_RESPONSE, self.format)
            + self.information_data
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Find_Information_Response:
        fmt = data[1]
        return cls(format=fmt, information_data=data[2:])


@dataclass
class ATT_Find_By_Type_Value_Request(ATTPdu):
    starting_handle: int = 0
    ending_handle: int = 0
    attribute_type: int = 0
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack(
                "<BHHH",
                ATTOpcode.FIND_BY_TYPE_VALUE_REQUEST,
                self.starting_handle,
                self.ending_handle,
                self.attribute_type,
            )
            + self.attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Find_By_Type_Value_Request:
        start, end, atype = struct.unpack_from("<HHH", data, 1)
        return cls(
            starting_handle=start,
            ending_handle=end,
            attribute_type=atype,
            attribute_value=data[7:],
        )


@dataclass
class ATT_Find_By_Type_Value_Response(ATTPdu):
    handles_info_list: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.FIND_BY_TYPE_VALUE_RESPONSE]) + self.handles_info_list

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Find_By_Type_Value_Response:
        return cls(handles_info_list=data[1:])


@dataclass
class ATT_Read_By_Type_Request(ATTPdu):
    starting_handle: int = 0
    ending_handle: int = 0
    attribute_type: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack(
                "<BHH",
                ATTOpcode.READ_BY_TYPE_REQUEST,
                self.starting_handle,
                self.ending_handle,
            )
            + self.attribute_type
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_By_Type_Request:
        start, end = struct.unpack_from("<HH", data, 1)
        return cls(
            starting_handle=start,
            ending_handle=end,
            attribute_type=data[5:],
        )


@dataclass
class ATT_Read_By_Type_Response(ATTPdu):
    length: int = 0
    attribute_data_list: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BB", ATTOpcode.READ_BY_TYPE_RESPONSE, self.length)
            + self.attribute_data_list
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_By_Type_Response:
        length = data[1]
        return cls(length=length, attribute_data_list=data[2:])


@dataclass
class ATT_Read_Request(ATTPdu):
    attribute_handle: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack("<BH", ATTOpcode.READ_REQUEST, self.attribute_handle)

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Request:
        (handle,) = struct.unpack_from("<H", data, 1)
        return cls(attribute_handle=handle)


@dataclass
class ATT_Read_Response(ATTPdu):
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.READ_RESPONSE]) + self.attribute_value

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Response:
        return cls(attribute_value=data[1:])


@dataclass
class ATT_Read_Blob_Request(ATTPdu):
    attribute_handle: int = 0
    value_offset: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack(
            "<BHH",
            ATTOpcode.READ_BLOB_REQUEST,
            self.attribute_handle,
            self.value_offset,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Blob_Request:
        handle, offset = struct.unpack_from("<HH", data, 1)
        return cls(attribute_handle=handle, value_offset=offset)


@dataclass
class ATT_Read_Blob_Response(ATTPdu):
    part_attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.READ_BLOB_RESPONSE]) + self.part_attribute_value

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Blob_Response:
        return cls(part_attribute_value=data[1:])


@dataclass
class ATT_Read_Multiple_Request(ATTPdu):
    set_of_handles: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.READ_MULTIPLE_REQUEST]) + self.set_of_handles

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Multiple_Request:
        return cls(set_of_handles=data[1:])


@dataclass
class ATT_Read_Multiple_Response(ATTPdu):
    set_of_values: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.READ_MULTIPLE_RESPONSE]) + self.set_of_values

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_Multiple_Response:
        return cls(set_of_values=data[1:])


@dataclass
class ATT_Read_By_Group_Type_Request(ATTPdu):
    starting_handle: int = 0
    ending_handle: int = 0
    attribute_group_type: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack(
                "<BHH",
                ATTOpcode.READ_BY_GROUP_TYPE_REQUEST,
                self.starting_handle,
                self.ending_handle,
            )
            + self.attribute_group_type
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_By_Group_Type_Request:
        start, end = struct.unpack_from("<HH", data, 1)
        return cls(
            starting_handle=start,
            ending_handle=end,
            attribute_group_type=data[5:],
        )


@dataclass
class ATT_Read_By_Group_Type_Response(ATTPdu):
    length: int = 0
    attribute_data_list: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BB", ATTOpcode.READ_BY_GROUP_TYPE_RESPONSE, self.length)
            + self.attribute_data_list
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Read_By_Group_Type_Response:
        length = data[1]
        return cls(length=length, attribute_data_list=data[2:])


@dataclass
class ATT_Write_Request(ATTPdu):
    attribute_handle: int = 0
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BH", ATTOpcode.WRITE_REQUEST, self.attribute_handle)
            + self.attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Write_Request:
        (handle,) = struct.unpack_from("<H", data, 1)
        return cls(attribute_handle=handle, attribute_value=data[3:])


@dataclass
class ATT_Write_Response(ATTPdu):
    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.WRITE_RESPONSE])

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Write_Response:
        return cls()


@dataclass
class ATT_Write_Command(ATTPdu):
    attribute_handle: int = 0
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BH", ATTOpcode.WRITE_COMMAND, self.attribute_handle)
            + self.attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Write_Command:
        (handle,) = struct.unpack_from("<H", data, 1)
        return cls(attribute_handle=handle, attribute_value=data[3:])


@dataclass
class ATT_Prepare_Write_Request(ATTPdu):
    attribute_handle: int = 0
    value_offset: int = 0
    part_attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack(
                "<BHH",
                ATTOpcode.PREPARE_WRITE_REQUEST,
                self.attribute_handle,
                self.value_offset,
            )
            + self.part_attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Prepare_Write_Request:
        handle, offset = struct.unpack_from("<HH", data, 1)
        return cls(
            attribute_handle=handle,
            value_offset=offset,
            part_attribute_value=data[5:],
        )


@dataclass
class ATT_Prepare_Write_Response(ATTPdu):
    attribute_handle: int = 0
    value_offset: int = 0
    part_attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack(
                "<BHH",
                ATTOpcode.PREPARE_WRITE_RESPONSE,
                self.attribute_handle,
                self.value_offset,
            )
            + self.part_attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Prepare_Write_Response:
        handle, offset = struct.unpack_from("<HH", data, 1)
        return cls(
            attribute_handle=handle,
            value_offset=offset,
            part_attribute_value=data[5:],
        )


@dataclass
class ATT_Execute_Write_Request(ATTPdu):
    flags: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack("<BB", ATTOpcode.EXECUTE_WRITE_REQUEST, self.flags)

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Execute_Write_Request:
        return cls(flags=data[1])


@dataclass
class ATT_Execute_Write_Response(ATTPdu):
    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.EXECUTE_WRITE_RESPONSE])

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Execute_Write_Response:
        return cls()


@dataclass
class ATT_Handle_Value_Notification(ATTPdu):
    attribute_handle: int = 0
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BH", ATTOpcode.HANDLE_VALUE_NOTIFICATION, self.attribute_handle)
            + self.attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Handle_Value_Notification:
        (handle,) = struct.unpack_from("<H", data, 1)
        return cls(attribute_handle=handle, attribute_value=data[3:])


@dataclass
class ATT_Handle_Value_Indication(ATTPdu):
    attribute_handle: int = 0
    attribute_value: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BH", ATTOpcode.HANDLE_VALUE_INDICATION, self.attribute_handle)
            + self.attribute_value
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Handle_Value_Indication:
        (handle,) = struct.unpack_from("<H", data, 1)
        return cls(attribute_handle=handle, attribute_value=data[3:])


@dataclass
class ATT_Handle_Value_Confirmation(ATTPdu):
    def to_bytes(self) -> bytes:
        return bytes([ATTOpcode.HANDLE_VALUE_CONFIRMATION])

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Handle_Value_Confirmation:
        return cls()


@dataclass
class ATT_Signed_Write_Command(ATTPdu):
    attribute_handle: int = 0
    attribute_value: bytes = field(default_factory=bytes)
    authentication_signature: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        return (
            struct.pack("<BH", ATTOpcode.SIGNED_WRITE_COMMAND, self.attribute_handle)
            + self.attribute_value
            + self.authentication_signature
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ATT_Signed_Write_Command:
        (handle,) = struct.unpack_from("<H", data, 1)
        # Last 12 bytes are the authentication signature
        return cls(
            attribute_handle=handle,
            attribute_value=data[3:-12] if len(data) > 15 else data[3:],
            authentication_signature=data[-12:] if len(data) > 15 else b"",
        )


# ---------------------------------------------------------------------------
# Opcode -> PDU class dispatcher
# ---------------------------------------------------------------------------

_OPCODE_MAP: dict[int, type[ATTPdu]] = {
    ATTOpcode.ERROR_RESPONSE: ATT_Error_Response,
    ATTOpcode.EXCHANGE_MTU_REQUEST: ATT_Exchange_MTU_Request,
    ATTOpcode.EXCHANGE_MTU_RESPONSE: ATT_Exchange_MTU_Response,
    ATTOpcode.FIND_INFORMATION_REQUEST: ATT_Find_Information_Request,
    ATTOpcode.FIND_INFORMATION_RESPONSE: ATT_Find_Information_Response,
    ATTOpcode.FIND_BY_TYPE_VALUE_REQUEST: ATT_Find_By_Type_Value_Request,
    ATTOpcode.FIND_BY_TYPE_VALUE_RESPONSE: ATT_Find_By_Type_Value_Response,
    ATTOpcode.READ_BY_TYPE_REQUEST: ATT_Read_By_Type_Request,
    ATTOpcode.READ_BY_TYPE_RESPONSE: ATT_Read_By_Type_Response,
    ATTOpcode.READ_REQUEST: ATT_Read_Request,
    ATTOpcode.READ_RESPONSE: ATT_Read_Response,
    ATTOpcode.READ_BLOB_REQUEST: ATT_Read_Blob_Request,
    ATTOpcode.READ_BLOB_RESPONSE: ATT_Read_Blob_Response,
    ATTOpcode.READ_MULTIPLE_REQUEST: ATT_Read_Multiple_Request,
    ATTOpcode.READ_MULTIPLE_RESPONSE: ATT_Read_Multiple_Response,
    ATTOpcode.READ_BY_GROUP_TYPE_REQUEST: ATT_Read_By_Group_Type_Request,
    ATTOpcode.READ_BY_GROUP_TYPE_RESPONSE: ATT_Read_By_Group_Type_Response,
    ATTOpcode.WRITE_REQUEST: ATT_Write_Request,
    ATTOpcode.WRITE_RESPONSE: ATT_Write_Response,
    ATTOpcode.WRITE_COMMAND: ATT_Write_Command,
    ATTOpcode.PREPARE_WRITE_REQUEST: ATT_Prepare_Write_Request,
    ATTOpcode.PREPARE_WRITE_RESPONSE: ATT_Prepare_Write_Response,
    ATTOpcode.EXECUTE_WRITE_REQUEST: ATT_Execute_Write_Request,
    ATTOpcode.EXECUTE_WRITE_RESPONSE: ATT_Execute_Write_Response,
    ATTOpcode.HANDLE_VALUE_NOTIFICATION: ATT_Handle_Value_Notification,
    ATTOpcode.HANDLE_VALUE_INDICATION: ATT_Handle_Value_Indication,
    ATTOpcode.HANDLE_VALUE_CONFIRMATION: ATT_Handle_Value_Confirmation,
    ATTOpcode.SIGNED_WRITE_COMMAND: ATT_Signed_Write_Command,
}


def decode_att_pdu(data: bytes) -> ATTPdu:
    """Decode raw bytes into the appropriate ATT PDU object."""
    if not data:
        raise ValueError("Empty ATT PDU data")
    opcode = data[0]
    pdu_cls = _OPCODE_MAP.get(opcode)
    if pdu_cls is None:
        raise ValueError(f"Unknown ATT opcode: 0x{opcode:02X}")
    return pdu_cls.from_bytes(data)


# ---------------------------------------------------------------------------
# ATTError exception
# ---------------------------------------------------------------------------

class ATTError(Exception):
    """Raised when the remote responds with an ATT Error Response."""

    def __init__(self, error_code: int) -> None:
        self.error_code = error_code
        super().__init__(f"ATT error: 0x{error_code:02X}")


# ---------------------------------------------------------------------------
# ATTBearer
# ---------------------------------------------------------------------------

class ATTBearer:
    """ATT protocol bearer -- sends requests and awaits responses over an L2CAP channel."""

    def __init__(self, channel: object, mtu: int = 23) -> None:
        self._channel = channel
        self._mtu = mtu
        self._pending: dict[int, asyncio.Future[ATTPdu]] = {}
        self._notification_handler: Callable[[int, bytes], Awaitable[None] | None] | None = None
        self._indication_handler: Callable[[int, bytes], Awaitable[None] | None] | None = None

    @property
    def mtu(self) -> int:
        return self._mtu

    async def exchange_mtu(self, mtu: int) -> int:
        req = ATT_Exchange_MTU_Request(client_rx_mtu=mtu)
        resp = await self._request(req, ATTOpcode.EXCHANGE_MTU_RESPONSE)
        if isinstance(resp, ATT_Exchange_MTU_Response):
            self._mtu = min(mtu, resp.server_rx_mtu)
            return self._mtu
        return self._mtu

    async def read(self, handle: int) -> bytes:
        req = ATT_Read_Request(attribute_handle=handle)
        resp = await self._request(req, ATTOpcode.READ_RESPONSE)
        if isinstance(resp, ATT_Read_Response):
            return resp.attribute_value
        if isinstance(resp, ATT_Error_Response):
            raise ATTError(resp.error_code)
        return b""

    async def write(self, handle: int, value: bytes) -> None:
        req = ATT_Write_Request(attribute_handle=handle, attribute_value=value)
        resp = await self._request(req, ATTOpcode.WRITE_RESPONSE)
        if isinstance(resp, ATT_Error_Response):
            raise ATTError(resp.error_code)

    async def write_without_response(self, handle: int, value: bytes) -> None:
        cmd = ATT_Write_Command(attribute_handle=handle, attribute_value=value)
        await self._channel.send(cmd.to_bytes())  # type: ignore[attr-defined]

    async def read_blob(self, handle: int, offset: int) -> bytes:
        req = ATT_Read_Blob_Request(attribute_handle=handle, value_offset=offset)
        resp = await self._request(req, ATTOpcode.READ_BLOB_RESPONSE)
        if isinstance(resp, ATT_Read_Blob_Response):
            return resp.part_attribute_value
        if isinstance(resp, ATT_Error_Response):
            raise ATTError(resp.error_code)
        return b""

    async def read_long(self, handle: int) -> bytes:
        result = await self.read(handle)
        if len(result) < (self._mtu - 1):
            return result
        offset = len(result)
        while True:
            chunk = await self.read_blob(handle, offset)
            result += chunk
            if len(chunk) < (self._mtu - 1):
                break
            offset += len(chunk)
        return result

    async def prepare_write(self, handle: int, offset: int, value: bytes) -> bytes:
        req = ATT_Prepare_Write_Request(
            attribute_handle=handle, value_offset=offset, part_attribute_value=value
        )
        resp = await self._request(req, ATTOpcode.PREPARE_WRITE_RESPONSE)
        if isinstance(resp, ATT_Prepare_Write_Response):
            return resp.part_attribute_value
        if isinstance(resp, ATT_Error_Response):
            raise ATTError(resp.error_code)
        return b""

    async def execute_write(self, flags: int) -> None:
        req = ATT_Execute_Write_Request(flags=flags)
        await self._request(req, ATTOpcode.EXECUTE_WRITE_RESPONSE)

    async def write_long(self, handle: int, value: bytes) -> None:
        chunk_size = self._mtu - 5
        for offset in range(0, len(value), chunk_size):
            await self.prepare_write(handle, offset, value[offset : offset + chunk_size])
        await self.execute_write(0x01)

    def set_notification_handler(
        self, handler: Callable[[int, bytes], Awaitable[None] | None] | None
    ) -> None:
        self._notification_handler = handler

    def set_indication_handler(
        self, handler: Callable[[int, bytes], Awaitable[None] | None] | None
    ) -> None:
        self._indication_handler = handler

    async def _request(self, pdu: ATTPdu, response_opcode: int) -> ATTPdu:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ATTPdu] = loop.create_future()
        self._pending[response_opcode] = fut
        # Also listen for error response
        self._pending[ATTOpcode.ERROR_RESPONSE] = fut
        await self._channel.send(pdu.to_bytes())  # type: ignore[attr-defined]
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        finally:
            self._pending.pop(response_opcode, None)
            self._pending.pop(ATTOpcode.ERROR_RESPONSE, None)

    async def _on_pdu(self, data: bytes) -> None:
        """Called when an ATT PDU arrives from the channel."""
        pdu = decode_att_pdu(data)
        opcode = data[0] if data else 0

        # Check if this resolves a pending request
        fut = self._pending.get(opcode)
        if fut is not None and not fut.done():
            fut.set_result(pdu)
            return

        # Handle notifications/indications
        if isinstance(pdu, ATT_Handle_Value_Notification) and self._notification_handler:
            result = self._notification_handler(pdu.attribute_handle, pdu.attribute_value)
            if asyncio.iscoroutine(result):
                await result
        elif isinstance(pdu, ATT_Handle_Value_Indication) and self._indication_handler:
            result = self._indication_handler(pdu.attribute_handle, pdu.attribute_value)
            if asyncio.iscoroutine(result):
                await result
            # Auto-confirm
            confirm = ATT_Handle_Value_Confirmation()
            await self._channel.send(confirm.to_bytes())  # type: ignore[attr-defined]
