"""GATT BTP service — translates GATT opcodes into Phase 1 IutActions / GATTServer / GATTClient calls.

See design spec §11.5 + auto-pts doc/btp_gatt.txt (2026-06-22 upstream-aligned).

Command handlers land in P.7 Tasks 2-8; this file is the skeleton.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
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


def _uuid_from_btp(uuid_bytes: bytes):
    """Convert auto-pts BTP UUID (2 or 16 LE bytes) -> UUID16/UUID128 object."""
    from pybluehost.core.uuid import UUID16, UUID128
    if len(uuid_bytes) == 2:
        return UUID16.from_bytes(uuid_bytes)
    if len(uuid_bytes) == 16:
        # BTP wire: 128-bit UUID in LE byte order. UUID128 stores BE internally,
        # so reverse.
        return UUID128(bytes(reversed(uuid_bytes)))
    raise ValueError(f"unsupported UUID length {len(uuid_bytes)}")


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


def _encode_characteristics(chars) -> bytes:
    """Encode discovered characteristics per BTP wire format.

    Each entry: handle(u16 LE) + properties(u8) + value_handle(u16 LE)
              + uuid_len(u8) + uuid_bytes.
    Prefixed with count(u8).
    """
    out = bytearray([len(chars) & 0xFF])
    for c in chars:
        out.extend(int(c.declaration_handle).to_bytes(2, "little"))
        out.append(int(c.properties) & 0xFF)
        out.extend(int(c.value_handle).to_bytes(2, "little"))
        out.append(len(c.uuid))
        out.extend(c.uuid)
    return bytes(out)


def _encode_services(services) -> bytes:
    """Encode [(start, end, uuid_bytes), ...] per auto-pts wire format.

    Wire layout per btp_gatt.txt:
      services_count (u8)
      [for each service]
        start_handle (u16 LE)
        end_handle   (u16 LE)
        uuid_len     (u8)  -- 2 or 16
        uuid_bytes         -- LE order on the wire (BTP-internal)
    """
    out = bytearray()
    out.append(len(services))
    for start, end, uuid_bytes in services:
        out.extend(start.to_bytes(2, "little"))
        out.extend(end.to_bytes(2, "little"))
        out.append(len(uuid_bytes))
        out.extend(uuid_bytes)
    return bytes(out)


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

    # ---- Set Value -------------------------------------------------------

    async def _handle_op_06(self, controller_index: int, data: bytes):
        """SET_VALUE (0x06) — update the stored value of an attribute by handle.

        BTP payload: u16 handle, u16 value_len, value_bytes.
        Emits 0x81 Attribute Value Changed event on success.
        """
        if len(data) < 4:
            return op.BTP_STATUS_FAILED, b""
        handle = int.from_bytes(data[0:2], "little")
        value_len = int.from_bytes(data[2:4], "little")
        if 4 + value_len > len(data):
            return op.BTP_STATUS_FAILED, b""
        attr = self._all_attrs.get(handle)
        if attr is None:
            return op.BTP_STATUS_FAILED, b""
        attr.value = bytes(data[4:4 + value_len])
        self._emit_attr_value_changed(handle, attr.value)
        return op.BTP_STATUS_SUCCESS, b""

    def _emit_attr_value_changed(self, handle: int, value: bytes) -> None:
        """Push the upstream 0x81 event to autoptsclient.

        Payload: handle(u16 LE) + data_len(u16 LE) + data.
        """
        if self._tester is None:
            return
        payload = (
            handle.to_bytes(2, "little")
            + len(value).to_bytes(2, "little")
            + bytes(value)
        )
        frame = BtpFrame(
            service=op.SERVICE_GATT,
            opcode=op.OP_GATT_EVENT_ATTR_VALUE_CHANGED,
            controller_index=self._controller_index,
            data=payload,
        )
        try:
            import asyncio
            import inspect
            coro = self._tester.emit_event(frame)
            if inspect.iscoroutine(coro):
                asyncio.create_task(coro)
        except RuntimeError:
            logger.exception("GATT attr-value-changed event: no event loop; dropping")

    # ---- Start Server ----------------------------------------------------

    async def _handle_op_07(self, controller_index: int, data: bytes):
        """START_SERVER (0x07) — commit pending GATT db to the stack's GATTServer.

        Iterates the pending service list and translates each _DynamicService
        into a ServiceDefinition for the real GATTServer.
        """
        from pybluehost.ble.gatt import (
            CharacteristicDefinition,
            DescriptorDefinition,
            ServiceDefinition,
        )

        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "gatt_server"):
            logger.warning("GATT START_SERVER: actions has no stack.gatt_server")
            return op.BTP_STATUS_FAILED, b""

        for dyn_svc in self._services:
            chars: list[CharacteristicDefinition] = []
            # svc.attributes contains declaration + value attrs in pairs.
            # We build one CharacteristicDefinition per value attr (skip decl).
            # Pattern: [decl0, val0, decl1, val1, ...] interleaved with descriptors.
            # We collect consecutive descriptors (is_descriptor=True) after each
            # value attr.
            i = 0
            attrs = dyn_svc.attributes
            while i < len(attrs):
                attr = attrs[i]
                if attr.is_characteristic:
                    # Two attrs per characteristic: declaration (i) + value (i+1)
                    if i + 1 < len(attrs) and attrs[i + 1].is_characteristic:
                        # i is declaration, i+1 is value handle
                        val_attr = attrs[i + 1]
                        i += 2
                    else:
                        val_attr = attr
                        i += 1
                    # Collect any descriptors that follow this value attr
                    descs: list[DescriptorDefinition] = []
                    while i < len(attrs) and attrs[i].is_descriptor:
                        d = attrs[i]
                        descs.append(DescriptorDefinition(
                            uuid=_uuid_from_btp(d.uuid),
                            permissions=d.permissions,
                            value=d.value,
                        ))
                        i += 1
                    chars.append(CharacteristicDefinition(
                        uuid=_uuid_from_btp(val_attr.uuid),
                        properties=val_attr.properties,
                        permissions=val_attr.permissions,
                        value=val_attr.value,
                        descriptors=descs,
                    ))
                else:
                    i += 1

            try:
                stack.gatt_server.add_service(ServiceDefinition(
                    uuid=_uuid_from_btp(dyn_svc.uuid),
                    is_primary=dyn_svc.primary,
                    characteristics=chars,
                ))
            except Exception:
                logger.exception("GATT START_SERVER: add_service raised")
                return op.BTP_STATUS_FAILED, b""

        return op.BTP_STATUS_SUCCESS, b""

    # ---- Reset Server ----------------------------------------------------

    async def _handle_op_08(self, controller_index: int, data: bytes):
        """RESET_SERVER (0x08) — clear the pending GATT db and attribute state."""
        self._services.clear()
        self._all_attrs.clear()
        self._next_handle = 1
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Client helpers --------------------------------------------------

    def _resolve_gatt_client(self, addr: bytes):
        """Find a GATTClient for the LE connection whose peer matches addr bytes."""
        try:
            session = self._actions.status()
        except Exception:
            return None
        for h, info in session.connections.items():
            peer_raw = (
                getattr(info.peer, "address", None)
                or getattr(info.peer, "bytes", None)
                or info.peer
            )
            if bytes(peer_raw)[:6] == bytes(addr)[:6]:
                return getattr(info, "gatt_client", None)
        return None

    # ---- Exchange MTU ----------------------------------------------------

    async def _handle_op_0a(self, controller_index: int, data: bytes):
        """EXCHANGE_MTU (0x0a) — body: addr_type(1)+addr(6)+mtu(u16 LE)."""
        if len(data) != 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        mtu = int.from_bytes(data[7:9], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            negotiated = await client.exchange_mtu(mtu)
        except Exception:
            logger.exception("GATT Exchange MTU raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, int(negotiated).to_bytes(2, "little")

    # ---- Discover All Primary Services ------------------------------------

    async def _handle_op_0b(self, controller_index: int, data: bytes):
        """DISC_ALL_PRIM_SVCS (0x0b) — body: addr_type(1)+addr(6)."""
        if len(data) != 7:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            services = await client.discover_all_services()
        except Exception:
            logger.exception("GATT DISC_ALL_PRIM_SVCS raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, _encode_services(services)

    # ---- Discover Primary Service by UUID ---------------------------------

    async def _handle_op_0c(self, controller_index: int, data: bytes):
        """DISC_PRIM_SVC_BY_UUID (0x0c) — body: addr_type(1)+addr(6)+uuid_len(1)+uuid_bytes."""
        if len(data) < 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        try:
            target_uuid, _ = _decode_uuid(data, offset=7)
        except ValueError:
            return op.BTP_STATUS_FAILED, b""
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            services = await client.discover_all_services()
        except Exception:
            logger.exception("GATT DISC_PRIM_SVC_BY_UUID raised")
            return op.BTP_STATUS_FAILED, b""
        filtered = [s for s in services if s[2] == target_uuid]
        return op.BTP_STATUS_SUCCESS, _encode_services(filtered)

    # ---- Find Included Services ------------------------------------------

    async def _handle_op_0d(self, controller_index: int, data: bytes):
        """FIND_INCLUDED_SVCS — not implemented in v1.0 GATTClient. Return FAILED."""
        return op.BTP_STATUS_FAILED, b""

    # ---- Discover All Characteristics ------------------------------------

    async def _handle_op_0e(self, controller_index: int, data: bytes):
        """DISC_ALL_CHRC — discover characteristics in [start, end]."""
        if len(data) != 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        start = int.from_bytes(data[7:9], "little")
        end = int.from_bytes(data[9:11], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            chars = await client.discover_characteristics(start, end)
        except Exception:
            logger.exception("GATT DISC_ALL_CHRC raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, _encode_characteristics(chars)

    # ---- Discover Characteristic by UUID ---------------------------------

    async def _handle_op_0f(self, controller_index: int, data: bytes):
        """DISC_CHRC_BY_UUID — filter discover_characteristics by uuid."""
        if len(data) < 12:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        start = int.from_bytes(data[7:9], "little")
        end = int.from_bytes(data[9:11], "little")
        try:
            target_uuid, _ = _decode_uuid(data, offset=11)
        except ValueError:
            return op.BTP_STATUS_FAILED, b""
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            chars = await client.discover_characteristics(start, end)
        except Exception:
            logger.exception("GATT DISC_CHRC_BY_UUID raised")
            return op.BTP_STATUS_FAILED, b""
        filtered = [c for c in chars if c.uuid == target_uuid]
        return op.BTP_STATUS_SUCCESS, _encode_characteristics(filtered)

    # ---- Discover All Descriptors ----------------------------------------

    async def _handle_op_10(self, controller_index: int, data: bytes):
        """DISC_ALL_DESC — discover descriptors in [start, end]."""
        if len(data) != 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        start = int.from_bytes(data[7:9], "little")
        end = int.from_bytes(data[9:11], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            descs = await client.discover_descriptors(start, end)
        except Exception:
            logger.exception("GATT DISC_ALL_DESC raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytearray([len(descs) & 0xFF])
        for d in descs:
            out.extend(d.handle.to_bytes(2, "little"))
            out.append(len(d.uuid))
            out.extend(d.uuid)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    # ---- Read variants ---------------------------------------------------

    async def _handle_op_11(self, controller_index: int, data: bytes):
        """READ — body: addr_type(1)+addr(6)+handle(u16 LE)."""
        if len(data) != 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:9], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            value = await client.read_characteristic(handle)
        except Exception:
            logger.exception("GATT READ raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytes([0x00]) + len(value).to_bytes(2, "little") + value
        return op.BTP_STATUS_SUCCESS, out

    async def _handle_op_13(self, controller_index: int, data: bytes):
        """READ_LONG — same body as READ; GATTClient.read_characteristic handles blobs."""
        return await self._handle_op_11(controller_index, data)

    async def _handle_op_14(self, controller_index: int, data: bytes):
        """READ_MULTIPLE — body: addr_type+addr+count(u8)+handles(2*count).
        Concatenates values from individual READs."""
        if len(data) < 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        count = data[7]
        if 8 + 2 * count > len(data):
            return op.BTP_STATUS_FAILED, b""
        handles = [
            int.from_bytes(data[8 + 2 * i : 10 + 2 * i], "little")
            for i in range(count)
        ]
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        chunks = bytearray()
        for h in handles:
            try:
                chunks.extend(await client.read_characteristic(h))
            except Exception:
                logger.exception("GATT READ_MULTIPLE handle 0x%04X raised", h)
                return op.BTP_STATUS_FAILED, b""
        out = bytes([0x00]) + len(chunks).to_bytes(2, "little") + bytes(chunks)
        return op.BTP_STATUS_SUCCESS, out

    # ---- Write variants --------------------------------------------------

    async def _handle_op_17(self, controller_index: int, data: bytes):
        """WRITE — body: addr_type+addr+handle+value_len(u16 LE)+value.
        Returns att_response(u8)."""
        if len(data) < 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:9], "little")
        value_len = int.from_bytes(data[9:11], "little")
        if 11 + value_len > len(data):
            return op.BTP_STATUS_FAILED, b""
        value = bytes(data[11:11 + value_len])
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await client.write_characteristic(handle, value)
        except Exception:
            logger.exception("GATT WRITE raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, bytes([0x00])

    async def _handle_op_15(self, controller_index: int, data: bytes):
        """WRITE_WITHOUT_RSP — same body as WRITE; ATT-level no-response."""
        return await self._handle_op_17(controller_index, data)

    async def _handle_op_18(self, controller_index: int, data: bytes):
        """WRITE_LONG — same body; GATTClient transparently prepares/executes."""
        return await self._handle_op_17(controller_index, data)

    async def _handle_op_19(self, controller_index: int, data: bytes):
        """WRITE_RELIABLE — same body; not distinguished at GATTClient surface."""
        return await self._handle_op_17(controller_index, data)

    # ---- Cfg Notify / Cfg Indicate (CCCD write) --------------------------

    async def _cfg_subscribe(self, data: bytes, *, enable_value: int) -> tuple[int, bytes]:
        if len(data) != 10:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        enable = data[7]
        cccd_handle = int.from_bytes(data[8:10], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        write_value = enable_value if enable else 0x0000
        try:
            await client.write_characteristic(cccd_handle, write_value.to_bytes(2, "little"))
        except Exception:
            logger.exception("GATT Cfg subscribe write raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1a(self, controller_index: int, data: bytes):
        """CFG_NOTIFY — enable=1 writes 0x0001 to CCCD; enable=0 writes 0x0000."""
        return await self._cfg_subscribe(data, enable_value=0x0001)

    async def _handle_op_1b(self, controller_index: int, data: bytes):
        """CFG_INDICATE — enable=1 writes 0x0002 to CCCD; enable=0 writes 0x0000."""
        return await self._cfg_subscribe(data, enable_value=0x0002)

    # ---- Notification event wiring --------------------------------------

    def attach_to_gatt_client(self, client, *, peer: bytes, addr_type: int) -> None:
        """Wire BTP event emission onto a v1.0 GATTClient's notification hook.

        When the peer sends a Handle Value Notification, the registered callback
        synthesises a BTP 0x80 event and pushes it via the bound tester.
        """
        import asyncio

        peer_bytes = bytes(peer)[:6]
        type_byte = int(addr_type) & 0xFF

        def _on_notification(char_handle: int, value: bytes):
            if self._tester is None:
                return
            payload = bytearray()
            payload.append(type_byte)
            payload.extend(peer_bytes)
            payload.extend(int(char_handle).to_bytes(2, "little"))
            payload.extend(len(value).to_bytes(2, "little"))
            payload.extend(value)
            frame = BtpFrame(
                service=op.SERVICE_GATT,
                opcode=op.OP_GATT_EVENT_NOTIFICATION,
                controller_index=self._controller_index,
                data=bytes(payload),
            )
            try:
                asyncio.create_task(self._tester.emit_event(frame))
            except RuntimeError:
                logger.exception("GATT notification: no event loop; dropping")

        client.on_notification(_on_notification)
