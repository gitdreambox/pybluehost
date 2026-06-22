"""GATT BTP service — translates GATT opcodes into Phase 1 IutActions / GATTServer / GATTClient calls.

See design spec §11.5 + auto-pts doc/btp_gatt.txt (2026-06-22 upstream-aligned).

Command handlers land in P.7 Tasks 2-8; this file is the skeleton.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)


@dataclass
class _DynamicAttribute:
    handle: int
    uuid: bytes
    properties: int = 0
    permissions: int = 0
    value: bytes = b""
    is_service: bool = False
    is_characteristic: bool = False
    is_descriptor: bool = False


@dataclass
class _DynamicService:
    handle: int
    uuid: bytes
    primary: bool = True
    attributes: list = field(default_factory=list)


def _decode_uuid(data: bytes, *, offset: int) -> tuple[bytes, int]:
    """Read auto-pts UUID format: u8 length followed by 2 or 16 bytes.

    Returns (uuid_bytes, new_offset). Raises ValueError if length is invalid
    or not enough bytes remain.
    """
    if offset >= len(data):
        raise ValueError("UUID length byte missing")
    length = data[offset]
    if length not in (2, 16):
        raise ValueError(f"unsupported UUID length {length}")
    if offset + 1 + length > len(data):
        raise ValueError("UUID truncated")
    return bytes(data[offset + 1 : offset + 1 + length]), offset + 1 + length


class GattService(BtpService):
    """GATT BTP service (both server-build and client-drive sides)."""

    SERVICE_ID = op.SERVICE_GATT

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._controller_index: int = 0
        # Server-side build state. Populated by Add Service / Add Characteristic /
        # Add Descriptor handlers; consumed by Start Server.
        self._pending_db: list = []
        self._services: list[_DynamicService] = []
        self._all_attrs: dict[int, _DynamicAttribute] = {}
        self._next_handle: int = 1

    def _allocate_handle(self) -> int:
        h = self._next_handle
        self._next_handle += 1
        return h

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported GATT opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """ADD_SERVICE (0x02) — declare a primary or secondary service.

        BTP payload: u8 svc_type (0=primary, 1=secondary), u8 uuid_length, uuid_bytes.
        Response: u16 service_handle (little-endian).
        """
        if len(data) < 2:
            return op.BTP_STATUS_FAILED, b""
        svc_type = data[0]
        try:
            uuid, _ = _decode_uuid(data, offset=1)
        except ValueError:
            return op.BTP_STATUS_FAILED, b""
        handle = self._allocate_handle()
        attr = _DynamicAttribute(handle=handle, uuid=uuid, is_service=True)
        svc = _DynamicService(
            handle=handle,
            uuid=uuid,
            primary=(svc_type == op.GATT_SERVICE_PRIMARY),
        )
        self._services.append(svc)
        self._all_attrs[handle] = attr
        return op.BTP_STATUS_SUCCESS, handle.to_bytes(2, "little")

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """ADD_CHARACTERISTIC (0x03) — add a characteristic to an existing service.

        BTP payload: u16 svc_handle, u8 properties, u8 permissions, u8 uuid_length, uuid_bytes.
        Response: u16 char_value_handle (little-endian).
        """
        if len(data) < 5:
            return op.BTP_STATUS_FAILED, b""
        svc_handle = int.from_bytes(data[0:2], "little")
        properties = data[2]
        permissions = data[3]
        # Find the service by handle
        parent_svc = next((s for s in self._services if s.handle == svc_handle), None)
        if parent_svc is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            uuid, _ = _decode_uuid(data, offset=4)
        except ValueError:
            return op.BTP_STATUS_FAILED, b""
        # Allocate declaration handle (char declaration attribute)
        decl_handle = self._allocate_handle()
        # Allocate value handle (the actual characteristic value attribute)
        value_handle = self._allocate_handle()
        decl_attr = _DynamicAttribute(
            handle=decl_handle,
            uuid=uuid,
            properties=properties,
            permissions=permissions,
            is_characteristic=True,
        )
        value_attr = _DynamicAttribute(
            handle=value_handle,
            uuid=uuid,
            properties=properties,
            permissions=permissions,
            is_characteristic=True,
        )
        parent_svc.attributes.append(decl_attr)
        parent_svc.attributes.append(value_attr)
        self._all_attrs[decl_handle] = decl_attr
        self._all_attrs[value_handle] = value_attr
        return op.BTP_STATUS_SUCCESS, value_handle.to_bytes(2, "little")

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """ADD_DESCRIPTOR (0x04) — add a descriptor to an existing characteristic.

        BTP payload: u16 char_value_handle, u8 permissions, u8 uuid_length, uuid_bytes.
        Response: u16 descriptor_handle (little-endian).
        """
        if len(data) < 4:
            return op.BTP_STATUS_FAILED, b""
        char_handle = int.from_bytes(data[0:2], "little")
        permissions = data[2]
        # Verify the referenced characteristic handle exists
        char_attr = self._all_attrs.get(char_handle)
        if char_attr is None or not char_attr.is_characteristic:
            return op.BTP_STATUS_FAILED, b""
        try:
            uuid, _ = _decode_uuid(data, offset=3)
        except ValueError:
            return op.BTP_STATUS_FAILED, b""
        handle = self._allocate_handle()
        desc_attr = _DynamicAttribute(
            handle=handle,
            uuid=uuid,
            permissions=permissions,
            is_descriptor=True,
        )
        self._all_attrs[handle] = desc_attr
        return op.BTP_STATUS_SUCCESS, handle.to_bytes(2, "little")
