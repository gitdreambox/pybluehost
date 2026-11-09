"""GATT BTP service — translates GATT opcodes into Phase 1 IutActions / GATTServer / GATTClient calls.

See design spec §11.5 + auto-pts doc/btp_gatt.txt (2026-06-22 upstream-aligned).

Command handlers land in P.7 Tasks 2-8; this file is the skeleton.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService


def _att_status_of(exc: Exception) -> "int | None":
    """ATT error code if ``exc`` is an ATTError, else None (genuine failure).

    Read/Write BTP responses carry the ATT error code in their ATT_Response byte
    (BTP_STATUS_SUCCESS at the BTP layer) so the PTS lower tester can verify the
    *expected* error in BI (error-handling) cases. Only non-ATT failures (no
    client, transport error) map to BTP_STATUS_FAILED.
    """
    from pybluehost.ble.att import ATTError
    return exc.error_code if isinstance(exc, ATTError) else None
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
    enc_key_size: int = 0      # SET_ENC_KEY_SIZE (0x09); enforcement is SMP-side
    is_service: bool = False
    is_characteristic: bool = False
    is_descriptor: bool = False
    is_include: bool = False
    # For an include declaration: the dynamic start handle of the included
    # service (ADD_INCLUDED_SERVICE's only payload field).
    include_target: int = 0


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


def _uuid_to_btp(uuid) -> bytes:
    """Convert a UUID16/UUID128 object -> auto-pts BTP LE wire bytes.

    Inverse of ``_uuid_from_btp``: UUID16 is already LE (``to_bytes``), UUID128
    is stored big-endian internally so it is reversed back to LE.
    """
    from pybluehost.core.uuid import UUID16, UUID128
    if isinstance(uuid, UUID16):
        return uuid.to_bytes()
    if isinstance(uuid, UUID128):
        return bytes(reversed(uuid.to_bytes()))
    # Fallback for raw bytes / unknown: return as-is.
    return bytes(uuid) if not isinstance(uuid, bytes) else uuid


def _standard_gap_gatt_services():
    """Standard GAP (0x1800) + GATT (0x1801) services a GATT server hosts natively.

    PTS GAP/GAT (Device Name / Appearance / PPCP) and GATT/SR/GAS (Service
    Changed / Database Hash / Client Supported Features) cases require these in
    the IUT's db, but auto-pts does NOT add them via BTP — zephyr hosts them
    natively, so we must too. Appended AFTER the BTP-built vendor service in
    START_SERVER so the vendor handle layout the passing GATT/SR cases depend
    on is unchanged (auto-pts discovers handles dynamically via GET_ATTRS).
    """
    from pybluehost.ble.ead import EAD_KEY_MATERIAL_LEN
    from pybluehost.ble.gatt import (
        CharacteristicDefinition, CharProperties, Permissions, ServiceDefinition,
    )
    from pybluehost.core.uuid import UUID16

    RW = Permissions.READABLE | Permissions.WRITABLE
    gap = ServiceDefinition(
        uuid=UUID16(0x1800),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A00),  # Device Name
                properties=CharProperties.READ | CharProperties.WRITE,
                permissions=RW, value=b"PyBlueHost"),
            CharacteristicDefinition(
                uuid=UUID16(0x2A01),  # Appearance
                properties=CharProperties.READ | CharProperties.WRITE,
                permissions=RW, value=b"\x00\x00"),
            CharacteristicDefinition(
                # Encrypted Data Key Material (Vol 3 Part C §12.6, CSS v15
                # §1.23): session key(16) + IV(8). GAP/ADV/BV-21 has the Lower
                # Tester read this from the IUT and then decrypt the Encrypted
                # Advertising Data we broadcast, so the server has to host it;
                # the value is filled in by SET_EAD_KEY_MATERIAL (0x31).
                uuid=UUID16(0x2B88),
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=bytes(EAD_KEY_MATERIAL_LEN)),
            CharacteristicDefinition(
                uuid=UUID16(0x2A04),  # Peripheral Preferred Connection Parameters
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=bytes([0x50, 0x00, 0xA0, 0x00, 0x00, 0x00, 0xF4, 0x01])),
            CharacteristicDefinition(
                uuid=UUID16(0x2AA6),  # Central Address Resolution (GAP/GAT/BV-18)
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                # 0x01 = supported. The stack really does resolve RPAs for the
                # initiator (resolving list + address resolution, see
                # actions.prepare_auto_connection), and GAP/CONN/ACEP BV-03's
                # preamble *requires* it: the LT reads this characteristic and
                # aborts the case ("doesn't enable address resolution") when it
                # reads 0x00. GAP/GAT/BV-18 only checks schema conformance, so
                # either value passes there.
                value=b"\x01"),
        ])
    gatt = ServiceDefinition(
        uuid=UUID16(0x1801),
        characteristics=[
            CharacteristicDefinition(
                uuid=UUID16(0x2A05),  # Service Changed (indicate-only)
                properties=CharProperties.INDICATE,
                permissions=Permissions.READABLE,
                value=b"\x00\x00\x00\x00"),  # start_handle(2) + end_handle(2)
            CharacteristicDefinition(
                uuid=UUID16(0x2B2A),  # Database Hash (GATT/SR/GAS/BV-02)
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=bytes(16)),  # refreshed from db.database_hash() on read
            CharacteristicDefinition(
                uuid=UUID16(0x2B29),  # Client Supported Features (GAS/BV-03/04)
                properties=CharProperties.READ | CharProperties.WRITE,
                permissions=RW,
                value=bytes(2)),
            CharacteristicDefinition(
                uuid=UUID16(0x2B3A),  # Server Supported Features
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=b"\x01"),  # octet 0 bit 0: EATT supported (Core Vol 3
                                 # Part G Table 7.11; GAW/BV-12, GAC/BI-01
                                 # initial conditions)
        ])
    return [gap, gatt]


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

    Each entry (auto-pts gatt_dec_chrc_attr, struct '<HHBB'):
      handle(u16 LE) + value_handle(u16 LE) + properties(u8)
      + uuid_len(u8) + uuid_bytes.
    Prefixed with count(u8).
    """
    out = bytearray([len(chars) & 0xFF])
    for c in chars:
        out.extend(int(c.declaration_handle).to_bytes(2, "little"))
        out.extend(int(c.value_handle).to_bytes(2, "little"))
        out.append(int(c.properties) & 0xFF)
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


def _encode_includes(includes) -> bytes:
    """Encode [(include_handle, inc_start, inc_end, uuid_bytes), ...] per auto-pts
    FIND_INCLUDED wire format (btp_gatt.txt 0x0d):
      services_count (u8)
      [for each include]
        include_handle (u16 LE)
        inc_start_handle (u16 LE)
        inc_end_handle   (u16 LE)
        uuid_len     (u8)  -- 2 or 16
        uuid_bytes         -- LE order on the wire
    """
    out = bytearray()
    out.append(len(includes))
    for incl_handle, inc_start, inc_end, uuid_bytes in includes:
        out.extend(incl_handle.to_bytes(2, "little"))
        out.extend(inc_start.to_bytes(2, "little"))
        out.extend(inc_end.to_bytes(2, "little"))
        out.append(len(uuid_bytes))
        out.extend(uuid_bytes)
    return bytes(out)


class GattService(BtpService):
    """GATT BTP service (both server-build and client-drive sides)."""

    SERVICE_ID = op.SERVICE_GATT

    # Preferred ATT MTU the IUT proposes in Exchange MTU (upstream BTP carries
    # no MTU field — the IUT chooses). 247 is the LE max per Core Spec.
    _PREFERRED_MTU = 247

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._controller_index: int = 0
        # Server-side build state. Populated by Add Service / Add Characteristic /
        # Add Descriptor handlers; consumed by Start Server.
        self._pending_db: list = []
        self._services: list[_DynamicService] = []
        self._all_attrs: dict[int, _DynamicAttribute] = {}
        # Per-connection Read-Multiple-Variable bearer rotation (GATT/CL/GAR/
        # BV-10: request #1 on the unenhanced ATT bearer, #2 on the EATT
        # bearer — BTP 0x20 has no bearer field, so the choice is ours).
        self._rmvl_bearer_seq: dict[int, int] = {}
        # In-flight transactions of a multiplexed RMVL sequence, keyed by
        # connection handle: {"att": future, "eatt": future}.
        self._rmvl_pending: dict[int, dict] = {}
        self._next_handle: int = 1
        # "Last added attribute" for the BTP in-sequence commands. ADD_CHAR /
        # ADD_DESC / SET_VALUE / SET_ENC_KEY_SIZE all accept id 0x0000 meaning
        # "the attribute most recently added" (btp_gatt.txt). Tracked here.
        self._last_attr: _DynamicAttribute | None = None
        # Service that owns the most recently added characteristic — the parent
        # an in-sequence ADD_DESCRIPTOR is appended to.
        self._last_char_parent: _DynamicService | None = None

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
            bit_index = code
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
        self._last_attr = attr
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
        # Service_ID 0x0000 = "add in sequence" (to the most recently declared
        # service); non-zero targets a specific service handle (btp_gatt.txt).
        if svc_handle == 0:
            parent_svc = self._services[-1] if self._services else None
        else:
            parent_svc = next(
                (s for s in self._services if s.handle == svc_handle), None)
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
        # "Last attribute" for in-sequence SET_VALUE / ADD_DESC is the value attr.
        self._last_attr = value_attr
        self._last_char_parent = parent_svc
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
        # Characteristic_ID 0x0000 = "add in sequence" — to the characteristic
        # most recently added (btp_gatt.txt). Non-zero targets that value handle.
        if char_handle == 0:
            char_attr = self._last_attr
            parent_svc = self._last_char_parent
        else:
            char_attr = self._all_attrs.get(char_handle)
            parent_svc = next(
                (s for s in self._services if char_attr in s.attributes), None)
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
        # Append to the owning service's attribute list (right after the char
        # value attr it belongs to) so START_SERVER commits it into the real db.
        if parent_svc is not None:
            try:
                idx = parent_svc.attributes.index(char_attr)
                parent_svc.attributes.insert(idx + 1, desc_attr)
            except ValueError:
                parent_svc.attributes.append(desc_attr)
        # In-sequence SET_VALUE after ADD_DESC targets the descriptor.
        self._last_attr = desc_attr
        return op.BTP_STATUS_SUCCESS, handle.to_bytes(2, "little")

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """ADD_INCLUDED_SERVICE (0x05) — include a previously-added service.

        BTP payload: u16 service_handle (little-endian) of the service to
        include. auto-pts' GATT/SR init_server sequence issues this right after
        adding the primary service (``gatts_add_svc(0, SVND16_1)`` →
        ``gatts_add_inc_svc(1)``).

        The include declaration must reach the on-air database: without it the
        secondary service is unreachable (a client discovers secondary services
        only through includes), so PTS' Database Hash view — GATT/SR/GAS/BV-02 —
        silently omits every attribute of it and disagrees with our hash. The
        declaration is materialised by START_SERVER (0x07) as a 0x2802
        attribute whose value is the included service's handle range + UUID.
        """
        if len(data) < 2:
            return op.BTP_STATUS_FAILED, b""
        target = int.from_bytes(data[0:2], "little")
        target_attr = self._all_attrs.get(target)
        if target_attr is None or not target_attr.is_service:
            return op.BTP_STATUS_FAILED, b""
        # The include declaration carries the standard «Include» UUID 0x2802.
        handle = self._allocate_handle()
        inc_attr = _DynamicAttribute(
            handle=handle,
            uuid=b"\x02\x28",  # 0x2802 little-endian
            is_include=True,
            include_target=target,
        )
        self._all_attrs[handle] = inc_attr
        # Attach to the most recently declared service (the one being built).
        if self._services:
            self._services[-1].attributes.append(inc_attr)
        return op.BTP_STATUS_SUCCESS, handle.to_bytes(2, "little")

    # ---- Set Value -------------------------------------------------------

    async def _handle_op_06(self, controller_index: int, data: bytes):
        """SET_VALUE (0x06) — update the stored value of an attribute by handle.

        BTP payload: u16 handle, u16 value_len, value_bytes.
        Emits 0x81 Attribute Value Changed event on success, and pushes the new
        value to every CCCD subscriber (see ``_push_value_to_subscribers``).
        """
        if len(data) < 4:
            return op.BTP_STATUS_FAILED, b""
        handle = int.from_bytes(data[0:2], "little")
        value_len = int.from_bytes(data[2:4], "little")
        if 4 + value_len > len(data):
            return op.BTP_STATUS_FAILED, b""
        value = bytes(data[4:4 + value_len])
        # Attribute_ID 0x0000 = "set last attribute in db value" (btp_gatt.txt).
        if handle == 0:
            if self._last_attr is None:
                return op.BTP_STATUS_FAILED, b""
            handle = self._last_attr.handle
        # The committed db is the authority for a handle named by the Lower
        # Tester: ``hdl_wid_98`` feeds GET_ATTRIBUTE_VALUE's handle straight into
        # SET_VALUE, and that handler reads ``server.db``. The BTP build map can
        # drift from it (``add_service`` auto-adds a CCCD for notify/indicate
        # characteristics declared without one, and the standard GAP/GATT
        # services are appended at commit time), so a handle that exists in the
        # real db may not exist in ``_all_attrs`` at all — GATT/SR/GAI/BV-01
        # targets handle 0x003B and used to fail here before the value could be
        # pushed.
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        db = getattr(server, "db", None) if server is not None else None
        attr = db.get(handle) if db is not None else None
        if attr is None:
            attr = self._all_attrs.get(handle)
        if attr is None:
            return op.BTP_STATUS_FAILED, b""
        attr.value = value
        self._emit_attr_value_changed(handle, value)
        await self._push_value_to_subscribers(handle, value)
        return op.BTP_STATUS_SUCCESS, b""

    async def _push_value_to_subscribers(self, handle: int, value: bytes) -> None:
        """Make the committed GATT server actually send the new value.

        ``SET_VALUE`` is the Upper Tester's only way to make the IUT host send a
        notification/indication — btp_gatt.txt has no dedicated opcode. auto-pts
        ``hdl_wid_92``/``hdl_wid_98`` have the Lower Tester enable the CCCD,
        then set the value and wait on the air for ATT_HANDLE_VALUE_NTF (0x1B)
        or ATT_HANDLE_VALUE_IND (0x1D) before answering the MMI. Only updating
        the dynamic attribute left PTS waiting until the time guard
        (GATT/SR/GAN/BV-01 PTS TIMEOUT)."""
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        if server is None:
            return
        try:
            await server.update_attribute_value(handle, value)
        except Exception:
            logger.exception(
                "GATT SET_VALUE: notify/indicate delivery raised (handle=0x%04X)",
                handle,
            )

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
            IncludeDefinition,
            ServiceDefinition,
        )

        stack = getattr(self._actions, "_stack", None)
        if stack is None or not hasattr(stack, "gatt_server"):
            logger.warning("GATT START_SERVER: actions has no stack.gatt_server")
            return op.BTP_STATUS_FAILED, b""

        # Dynamic service start handle -> handles assigned by the real db, so an
        # include declaration can name the range of a service added earlier.
        added: dict[int, object] = {}

        for dyn_svc in self._services:
            chars: list[CharacteristicDefinition] = []
            includes: list[IncludeDefinition] = [
                IncludeDefinition(
                    start_handle=added[attr.include_target].service_handle,
                    end_handle=added[attr.include_target].end_handle,
                    uuid=_uuid_from_btp(
                        self._all_attrs[attr.include_target].uuid),
                )
                for attr in dyn_svc.attributes
                if attr.is_include and attr.include_target in added
            ]
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
                            enc_key_size=getattr(d, "enc_key_size", 0),
                        ))
                        i += 1
                    chars.append(CharacteristicDefinition(
                        uuid=_uuid_from_btp(val_attr.uuid),
                        properties=val_attr.properties,
                        permissions=val_attr.permissions,
                        value=val_attr.value,
                        descriptors=descs,
                        enc_key_size=getattr(val_attr, "enc_key_size", 0),
                        # The value auto-pts declared for this characteristic is
                        # its size; PTS writes something longer than that in the
                        # "Attribute Value Length Too Long" cases and expects
                        # ATT 0x0D (GATT/SR/GAW/BI-32/33/39/40).
                        max_length=len(val_attr.value) or None,
                    ))
                    logger.debug(
                        "GATT START_SERVER: char uuid=%s value_len=%d max_length=%s",
                        val_attr.uuid.hex(), len(val_attr.value),
                        len(val_attr.value) or None,
                    )
                else:
                    i += 1

            try:
                handles = stack.gatt_server.add_service(ServiceDefinition(
                    uuid=_uuid_from_btp(dyn_svc.uuid),
                    is_primary=dyn_svc.primary,
                    characteristics=chars,
                    includes=includes,
                ))
            except Exception:
                logger.exception("GATT START_SERVER: add_service raised")
                return op.BTP_STATUS_FAILED, b""
            added[dyn_svc.handle] = handles
            if includes:
                logger.debug(
                    "GATT START_SERVER: service 0x%04X includes %s",
                    handles.service_handle,
                    [(hex(i.start_handle), hex(i.end_handle)) for i in includes],
                )

        # Host the standard GAP (0x1800) + GATT (0x1801) services natively, AFTER
        # the BTP-built services so the vendor handle layout is unchanged. PTS
        # GAP/GAT + GATT/SR/GAS cases require these; auto-pts does not add them.
        for std_svc in _standard_gap_gatt_services():
            try:
                stack.gatt_server.add_service(std_svc)
            except Exception:
                logger.exception("GATT START_SERVER: standard service add raised")
                return op.BTP_STATUS_FAILED, b""

        # A mid-test db change (GAS/BV-06 WID 136 adds a service) must notify
        # Service Changed subscribers: the Lower Tester waits for the indication.
        # On the initial build there is no connection yet, so these are no-ops.
        marker = getattr(stack.gatt_server, "mark_database_changed", None)
        if callable(marker):
            marker()
        try:
            await stack.gatt_server.indicate_service_changed(
                0x0001, stack.gatt_server.db.last_handle)
        except Exception:
            logger.exception("GATT START_SERVER: indicate_service_changed raised")

        return op.BTP_STATUS_SUCCESS, b""

    # ---- Reset Server ----------------------------------------------------

    async def _handle_op_08(self, controller_index: int, data: bytes):
        """RESET_SERVER (0x08) — clear the pending GATT db and attribute state."""
        self._services.clear()
        self._all_attrs.clear()
        self._next_handle = 1
        self._last_attr = None
        self._last_char_parent = None
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_09(self, controller_index: int, data: bytes):
        """SET_ENC_KEY_SIZE (0x09) — record the required encryption key size.

        BTP payload: u16 handle, u8 enc_key_size. Stored on the attribute; the
        GATT server consults it when checking encryption-key-size permissions
        (enforcement rides on the SMP/link-key path).
        """
        if len(data) < 3:
            return op.BTP_STATUS_FAILED, b""
        handle = int.from_bytes(data[0:2], "little")
        # Attribute_ID 0x0000 = "last added attribute" (btp_gatt.txt).
        if handle == 0:
            attr = self._last_attr
        else:
            attr = self._all_attrs.get(handle)
        if attr is None:
            return op.BTP_STATUS_FAILED, b""
        attr.enc_key_size = data[2]
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1c(self, controller_index: int, data: bytes):
        """GET_ATTRIBUTES (0x1c) — enumerate the *committed* GATT server db.

        BTP payload: u16 start_handle, u16 end_handle, u8 type_length,
        type_bytes (0/2/16). Response: u8 count, then per attribute
        u16 handle + u8 permission + u8 type_length + type_bytes (LE).

        auto-pts' GATT/SR WID handlers call ``gatts_get_attrs`` to verify the
        services the IUT actually exposes, so this must read the real on-air
        ``GATTServer`` db (with its real handles), not the BTP-side build state.
        """
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        db = getattr(server, "db", None) if server is not None else None
        if db is None:
            return op.BTP_STATUS_FAILED, b""
        if len(data) < 5:
            return op.BTP_STATUS_FAILED, b""
        start = int.from_bytes(data[0:2], "little")
        end = int.from_bytes(data[2:4], "little")
        type_len = data[4]
        want: bytes | None = None
        if type_len:
            if type_len not in (2, 16) or 5 + type_len > len(data):
                return op.BTP_STATUS_FAILED, b""
            want = bytes(data[5:5 + type_len])

        out = bytearray()
        count = 0
        for attr in getattr(db, "_attrs", []):
            if not (start <= attr.handle <= end):
                continue
            type_btp = _uuid_to_btp(attr.type_uuid)
            if want is not None and type_btp != want:
                continue
            out += attr.handle.to_bytes(2, "little")
            out.append(int(attr.permissions) & 0xFF)
            out.append(len(type_btp) & 0xFF)
            out += type_btp
            count += 1
            if count == 0xFF:        # response count field is a single octet
                break
        return op.BTP_STATUS_SUCCESS, bytes([count]) + bytes(out)

    async def _handle_op_1d(self, controller_index: int, data: bytes):
        """GET_ATTRIBUTE_VALUE (0x1d) — read an attribute value from the db.

        BTP payload: u8 address_type, u8[6] address, u16 handle. Response:
        u8 att_response + u16 value_length (LE) + value bytes.

        ``att_response`` is the error code a *real* ATT read would produce under
        the requesting peer's link security, not just 0x00. auto-pts' WID 112/113
        ("…that requires read authorization") and WID 121/122 ("…that returns
        Insufficient Encryption Key Size") pick their target characteristic by
        matching this code (0x08 / 0x0C), so answering 0x00 unconditionally left
        them with no candidate and they returned '0000'.
        """
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        db = getattr(server, "db", None) if server is not None else None
        if db is None:
            return op.BTP_STATUS_FAILED, b""
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        handle = int.from_bytes(data[7:9], "little")
        attr = db.get(handle)
        if attr is None:
            # ATT Response 0x0A = Attribute Not Found; still a valid response.
            return op.BTP_STATUS_SUCCESS, bytes([0x0A]) + (0).to_bytes(2, "little")
        err = server._read_error(attr, self._link_security(server, data[1:7]))
        if err is not None:
            return op.BTP_STATUS_SUCCESS, bytes([err]) + (0).to_bytes(2, "little")
        value = bytes(attr.value)
        return (op.BTP_STATUS_SUCCESS,
                bytes([0x00]) + len(value).to_bytes(2, "little") + value)

    def _link_security(self, server, addr: bytes):
        """Link security of the peer named by a BTP wire address (LE order).

        GET_ATTRIBUTE_VALUE is a pure db query, so PTS calls it at points where
        the peer may not be connected at all — an unresolved peer therefore gets
        the default (unencrypted / unauthenticated / key_size 0) state, which is
        what makes WID 112/113's read_authz lookup resolve to 0x08.
        """
        from pybluehost.ble.gatt import _ConnSecurity

        handle = self._resolve_le_handle(addr)
        if handle is None:
            return _ConnSecurity()
        return server._security(handle)

    async def _handle_op_1e(self, controller_index: int, data: bytes):
        """CHANGE_DATABASE (0x1e) — mark a db change and emit a Service Changed
        indication to every connection with the Service Changed CCCD enabled.

        BTP payload: u16 start_handle + u16 end_handle + u8 visibility
        (0x00=Remove/0x01=Add/0x02=Any). start==end==0 -> the IUT picks the
        range (we use the whole db), matching auto-pts
        ``gatts_change_database(0, 0, 0x02)`` (GATT/SR/GAS/BV-01 WID 132).
        """
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        db = getattr(server, "db", None) if server is not None else None
        if db is None:
            return op.BTP_STATUS_FAILED, b""
        if len(data) < 5:
            return op.BTP_STATUS_FAILED, b""
        start = int.from_bytes(data[0:2], "little")
        end = int.from_bytes(data[2:4], "little")
        if start == 0 and end == 0:
            start, end = 0x0001, db.last_handle
        # Robust Caching (§2.5.2.1): a db change makes every connected client
        # change-unaware — the SC indication below re-syncs the single-bearer
        # ones, the rest must re-read the Database Hash.
        marker = getattr(server, "mark_database_changed", None)
        if callable(marker):
            marker()
        try:
            await server.indicate_service_changed(start, end)
        except Exception:
            logger.exception("GATT CHANGE_DATABASE: indicate_service_changed raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1f(self, controller_index: int, data: bytes):
        """EATT_CONNECT (0x1f) — body addr_type(1) + addr(6) + num(1).

        Establish `num` Enhanced ATT bearers to the peer, i.e. Enhanced
        Credit-Based channels on the fixed EATT SPSM (0x0027). auto-pts drives
        this from WID 255 for L2CAP/TIM/BV-03-C — the only L2CAP case that needs
        EATT — and its handler tolerates our failing it, but the case's pass
        verdict still requires the IUT to put a connection request on the air and
        to honour the collision back-off, which is what the manager does here.
        """
        if len(data) != 8:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        num = data[7] or 1
        stack = getattr(self._actions, "_stack", None)
        l2cap = getattr(stack, "l2cap", None) if stack is not None else None
        if l2cap is None:
            return op.BTP_STATUS_FAILED, b""
        handle = self._resolve_le_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            channels = await l2cap.connect_eatt_channels(handle, num=num)
        except Exception:
            logger.exception("GATT EATT_CONNECT failed handle=0x%04X", handle)
            return op.BTP_STATUS_FAILED, b""
        # Attach the GATT server to each new bearer so the Lower Tester's ATT
        # requests on them are answered (GATT/SR GAR/BV-11/12, GAW/BV-12,
        # GPM/BV-05). TIM/BV-03 needs only the on-air request + collision
        # back-off — attaching is harmless there (no requests arrive).
        try:
            attach = getattr(stack, "attach_eatt_bearer", None)
            if callable(attach):
                for ch in channels:
                    attach(ch)
        except Exception:
            logger.exception("GATT EATT_CONNECT attach failed handle=0x%04X", handle)
            return op.BTP_STATUS_FAILED, b""
        # Register a GATT-CLIENT ATT bearer per channel too — GAR/BV-10 sends
        # its second Read Multiple Variable request on the EATT bearer (the
        # server attach alone leaves the bearer server-only).
        try:
            client_reg = getattr(self._actions, "attach_eatt_client_bearer", None)
            if callable(client_reg):
                for ch in channels:
                    client_reg(handle, ch)
        except Exception:
            logger.exception(
                "GATT EATT_CONNECT client-bearer registration failed handle=0x%04X",
                handle)
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    def _resolve_le_handle(self, addr: bytes) -> int | None:
        """Handle of the LE connection whose peer matches the BTP wire address."""
        try:
            session = self._actions.status()
        except Exception:
            return None
        want = bytes(addr)[:6]
        for h, info in session.connections.items():
            if getattr(info, "transport", None) != "le":
                continue
            peer = getattr(info, "peer", None)
            if peer is None:
                continue
            to_hci = getattr(peer, "to_hci", None)
            if callable(to_hci):
                peer_wire = bytes(to_hci())[:6]
            else:
                peer_wire = bytes(
                    getattr(peer, "address", None)
                    or getattr(peer, "bytes", None)
                    or peer
                )[:6]
            if peer_wire == want:
                return h
        return None

    def _resolve_gatt_client(self, addr: bytes):
        """Find a GATTClient for the LE connection whose peer matches addr bytes.

        ``addr`` is the 6-byte BTP wire address (little-endian). Real BDAddress
        stores canonical big-endian in ``.address``, so normalise both sides to
        the wire (little-endian) form via ``to_hci`` before comparing.
        """
        try:
            session = self._actions.status()
        except Exception:
            return None
        want = bytes(addr)[:6]
        for h, info in session.connections.items():
            peer = info.peer
            to_hci = getattr(peer, "to_hci", None)
            if callable(to_hci):
                peer_wire = bytes(to_hci())[:6]
            else:
                peer_wire = bytes(
                    getattr(peer, "address", None)
                    or getattr(peer, "bytes", None)
                    or peer
                )[:6]
            if peer_wire == want:
                # Lazily build a GATT client for peripheral (incoming) links —
                # they register with gatt_client=None, but the IUT still acts as
                # a GATT client toward PTS on them (e.g. GAP/SEC WID 227 write).
                factory = getattr(self._actions, "gatt_client_for_handle", None)
                if callable(factory):
                    client = factory(info.handle)
                    if client is not None:
                        self._wire_notif_events(client, info, want)
                        return client
                client = getattr(info, "gatt_client", None)
                if client is not None:
                    self._wire_notif_events(client, info, want)
                return client
        return None

    def _wire_notif_events(self, client, conn_info, peer_wire: bytes) -> None:
        """Attach BTP notification/indication forwarding to a resolved client.

        The connection-up hook (pts_tester) fires before the lazily-created
        client exists, so wiring must also happen here — at first use — or
        incoming notifications/indications never reach auto-pts (PTS GATT/CL
        GAN/GAI and GAP/SEC/SEM BV-56..67).
        """
        peer = getattr(conn_info, "peer", None)
        atype_attr = getattr(peer, "type", 0)
        addr_type = int(getattr(atype_attr, "value", atype_attr) or 0)
        stack = getattr(self._actions, "_stack", None)
        handle = getattr(conn_info, "handle", None)
        try:
            self.attach_to_gatt_client(
                client, peer=peer_wire, addr_type=addr_type,
                conn_handle=handle,
                is_encrypted=getattr(stack, "is_le_encrypted", None),
                encrypt_pending=getattr(stack, "is_le_encrypt_pending", None),
            )
        except Exception:
            logger.exception("GATT: failed to wire notification events")

    # ---- Exchange MTU ----------------------------------------------------

    async def _handle_op_0a(self, controller_index: int, data: bytes):
        """EXCHANGE_MTU (0x0a) — body: addr_type(1)+addr(6).

        Upstream btp_gatt.txt carries no MTU field: the IUT proposes its own
        preferred ATT MTU. Response is empty.
        """
        if len(data) < 7:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await client.exchange_mtu(self._PREFERRED_MTU)
        except Exception:
            logger.exception("GATT Exchange MTU raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

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
        """FIND_INCLUDED_SVCS (0x0d) — body: addr_type(1)+addr(6)+start(2)+end(2).

        Discover Include declarations (ATT Read By Type, 0x2802) in the range and
        return them per the auto-pts wire format (PTS GATT/CL/GAD include tests).
        """
        if len(data) != 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        start = int.from_bytes(data[7:9], "little")
        end = int.from_bytes(data[9:11], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        discover = getattr(client, "discover_included_services", None)
        if discover is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            includes = await discover(start, end)
        except Exception:
            logger.exception("GATT FIND_INCLUDED_SVCS raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, _encode_includes(includes)

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
        """READ — body: addr_type(1)+addr(6)+handle(u16 LE).

        Response: att_response(u8)+value_len(u16 LE)+value. On ATT error the
        ATT_Response carries the error code with zero-length value (BI cases
        verify the expected error), not a BTP-layer failure.
        """
        if len(data) != 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:9], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            # BTP READ semantics = the reference stacks' `bt_gatt_read` /
            # gatt-client read: return the FULL attribute value (ATT Read +
            # Read Blob continuation). A single Read would return only the
            # first ATT_MTU-1 bytes and leave PTS waiting for the rest of the
            # procedure (GATT/CL/GAR/BV-04). For values that fit in one PDU no
            # Blob is sent — single-read cases are unaffected.
            value = await client.read_long_characteristic(handle)
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att]) + (0).to_bytes(2, "little")
            logger.exception("GATT READ raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytes([0x00]) + len(value).to_bytes(2, "little") + value
        return op.BTP_STATUS_SUCCESS, out

    async def _handle_op_13(self, controller_index: int, data: bytes):
        """READ_LONG — body: addr_type(1)+addr(6)+handle(u16)+offset(u16).

        Uses ATT Read + Read Blob pagination (a plain Read would return only the
        first MTU-1 bytes and leave PTS waiting for the rest). Response:
        att_response(u8)+value_len(u16)+value.
        """
        if len(data) != 11:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:9], "little")
        offset = int.from_bytes(data[9:11], "little")
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            value = await client.read_long_characteristic(handle, offset=offset)
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att]) + (0).to_bytes(2, "little")
            logger.exception("GATT READ_LONG raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytes([0x00]) + len(value).to_bytes(2, "little") + value
        return op.BTP_STATUS_SUCCESS, out

    async def _handle_op_12(self, controller_index: int, data: bytes):
        """READ_UUID — body: addr_type(1)+addr(6)+start(u16)+end(u16)+uuid_len(1)+uuid.

        Response: ATT_Response(1)+count(1)+[handle(u16)+data_len(1)+data]*.
        """
        if len(data) < 12:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        start = int.from_bytes(data[7:9], "little")
        end = int.from_bytes(data[9:11], "little")
        uuid_len = data[11]
        if uuid_len not in (2, 16) or 12 + uuid_len > len(data):
            return op.BTP_STATUS_FAILED, b""
        uuid = bytes(data[12:12 + uuid_len])
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            att_status, values = await client.read_using_characteristic_uuid(
                start, end, uuid
            )
        except Exception:
            logger.exception("GATT READ_UUID raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytearray([att_status & 0xFF, len(values) & 0xFF])
        for handle, value in values:
            out.extend(handle.to_bytes(2, "little"))
            out.append(len(value) & 0xFF)
            out.extend(value)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_14(self, controller_index: int, data: bytes):
        """READ_MULTIPLE — body: addr_type+addr+count(u8)+handles(2*count).

        Sends a single ATT Read Multiple Request (the PTS lower tester verifies
        that specific PDU; per-handle individual Reads don't satisfy it).
        Response: att_response(u8)+value_len(u16 LE)+concatenated values.
        """
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
        try:
            values = await client.read_multiple_characteristic(handles)
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att]) + (0).to_bytes(2, "little")
            logger.exception("GATT READ_MULTIPLE raised")
            return op.BTP_STATUS_FAILED, b""
        out = bytes([0x00]) + len(values).to_bytes(2, "little") + values
        return op.BTP_STATUS_SUCCESS, out

    async def _handle_op_20(self, controller_index: int, data: bytes):
        """READ_MULTIPLE_VAR — body: addr_type+addr+count(u8)+handles(2*count).

        Sends a single ATT Read Multiple Variable Length Request. Response:
        att_response(u8)+total_data_len(u16 LE)+data, where data is the RAW
        concatenation of the values (no per-value length prefixes) — upstream's
        gattc_read_multiple_var_rsp decodes the payload with gatt_dec_read_rsp
        (<BH + raw bytes) and hexlifies the whole blob for the WID-55 substring
        check, so length prefixes would make GAR/BV-08-C unsatisfiable.
        """
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
        try:
            # GATT.TS §4.6.1 (GAR/BV-10): the first RMVL request goes on the
            # unenhanced ATT bearer, the second on the EATT bearer, and BOTH
            # must be on air while both are pending — the Lower Tester answers
            # the ATT-bearer request only after the EATT-bearer request
            # arrives. BTP commands are dispatched serially, so the first
            # command of a multiplexed sequence fires both transactions and
            # the second one collects the EATT future. With no EATT bearer
            # this is a no-op (BV-08 single-bearer behaviour unchanged).
            handle = getattr(client, "connection_handle", None)
            factory = getattr(self._actions, "eatt_client_bearers_for_handle", None)
            eatt_bearers = (
                list(factory(handle) or [])
                if handle is not None and callable(factory) else []
            )
            if eatt_bearers:
                state = self._rmvl_pending.setdefault(handle, {})
                seq = self._rmvl_bearer_seq.get(handle, 0)
                self._rmvl_bearer_seq[handle] = seq + 1
                role = "att" if seq % 2 == 0 else "eatt"
                if role == "att" and "eatt" not in state:
                    default_bearer = (getattr(client, "default_bearer", None)
                                      or client._bearer)
                    state["att"] = asyncio.ensure_future(
                        client.read_multiple_variable_characteristic(
                            handles, bearer=default_bearer))
                    state["eatt"] = asyncio.ensure_future(
                        client.read_multiple_variable_characteristic(
                            handles, bearer=eatt_bearers[0]))
                fut = state.pop(role, None)
                if fut is not None:
                    values = await fut
                else:
                    bearer = (eatt_bearers[0] if role == "eatt"
                              else getattr(client, "default_bearer", None)
                              or client._bearer)
                    values = await client.read_multiple_variable_characteristic(
                        handles, bearer=bearer)
            else:
                values = await client.read_multiple_variable_characteristic(handles)
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att]) + (0).to_bytes(2, "little")
            logger.exception("GATT READ_MULTIPLE_VAR raised")
            return op.BTP_STATUS_FAILED, b""
        blob = b"".join(values)
        out = bytes([0x00]) + len(blob).to_bytes(2, "little") + blob
        return op.BTP_STATUS_SUCCESS, out

    async def _handle_op_21(self, controller_index: int, data: bytes):
        """NOTIFY_MULTIPLE (0x21) — body: addr_type+addr+cnt(u16 LE)+handles(2*cnt).

        The Upper Tester asks the IUT (GATT server) to send an ATT Multiple
        Handle Value Notification (0x23) with the values of `handles`. The IUT
        only sends it when the client enabled the Multiple Handle Value
        Notifications CSF bit (GAN/BV-02 step 7: a client without it is ignored).
        """
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        cnt = int.from_bytes(data[7:9], "little")
        if 9 + 2 * cnt > len(data):
            return op.BTP_STATUS_FAILED, b""
        handles = [
            int.from_bytes(data[9 + 2 * i : 11 + 2 * i], "little")
            for i in range(cnt)
        ]
        handle = self._resolve_le_handle(addr)
        if handle is None:
            return op.BTP_STATUS_FAILED, b""
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        if server is None or not hasattr(server, "notify_multiple"):
            return op.BTP_STATUS_FAILED, b""
        await server.notify_multiple(handle, handles)
        return op.BTP_STATUS_SUCCESS, b""

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
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att])
            logger.exception("GATT WRITE raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, bytes([0x00])

    async def _handle_op_15(self, controller_index: int, data: bytes):
        """WRITE_WITHOUT_RSP — same body as WRITE; ATT-level no-response."""
        return await self._handle_op_17(controller_index, data)

    async def _handle_op_18(self, controller_index: int, data: bytes):
        """WRITE_LONG — body: addr_type+addr+handle(u16)+offset(u16)+value_len(u16)+value.

        Uses the ATT Prepare/Execute Write procedure (not a single Write Request):
        the PTS lower tester explicitly prompts for "prepare write request" and
        verifies the long-write procedure, so a plain write leaves PTS waiting.
        Returns att_response(u8).
        """
        if len(data) < 13:
            return op.BTP_STATUS_FAILED, b""
        addr = bytes(data[1:7])
        handle = int.from_bytes(data[7:9], "little")
        offset = int.from_bytes(data[9:11], "little")
        value_len = int.from_bytes(data[11:13], "little")
        if 13 + value_len > len(data):
            return op.BTP_STATUS_FAILED, b""
        value = bytes(data[13:13 + value_len])
        client = self._resolve_gatt_client(addr)
        if client is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await client.write_long_characteristic(handle, value, offset=offset)
        except Exception as exc:
            att = _att_status_of(exc)
            if att is not None:
                return op.BTP_STATUS_SUCCESS, bytes([att])
            logger.exception("GATT WRITE_LONG raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, bytes([0x00])

    async def _handle_op_19(self, controller_index: int, data: bytes):
        """WRITE_RELIABLE — same body as WRITE_LONG (with offset). Approximated by
        the Prepare/Execute path (true reliable write also verifies each prepare
        echo; close enough for the lower tester's procedure check)."""
        return await self._handle_op_18(controller_index, data)

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

    def attach_to_gatt_client(
        self, client, *, peer: bytes, addr_type: int,
        conn_handle: int | None = None,
        is_encrypted=None, encrypt_pending=None,
    ) -> None:
        """Wire BTP event emission onto a v1.0 GATTClient (delegates to bearer)."""
        bearer = getattr(client, "_bearer", None)
        if bearer is not None:
            self.attach_to_att_bearer(
                bearer, peer=peer, addr_type=addr_type, conn_handle=conn_handle,
                is_encrypted=is_encrypted, encrypt_pending=encrypt_pending)

    def attach_to_att_bearer(
        self, bearer, *, peer: bytes, addr_type: int,
        conn_handle: int | None = None,
        is_encrypted=None, encrypt_pending=None,
    ) -> None:
        """Wire BTP notification/indication forwarding onto an ATT bearer.

        When the peer sends a Handle Value Notification (0x1b) or Indication
        (0x1d), the registered callback synthesises a BTP 0x80 event and pushes
        it via the bound tester so auto-pts's ``stack.gatt.notification_events``
        sees it. Indications are auto-confirmed by the ATT bearer regardless.

        Event payload matches auto-pts ``gattc_dec_notification_ev_data``:
        ``addr_type(1) + addr(6) + notification_type(1) + handle(2) +
        data_len(2) + data`` — notification_type is 1=notification, 2=indication.

        Security drop (PTS GAP/SEC/SEM BV-56..67): when the link is not yet
        encrypted but a bonded-reconnect re-encryption is in flight
        (``encrypt_pending``), the event is *dropped* — confirmed at the ATT
        layer but never reported to the Upper Tester (GAP.TS step 9A.4/9B.4).
        On an unencrypted link with no encryption expected (plain GATT/CL
        GAN/GAI), events forward immediately.

        Idempotent per bearer: safe to call again (connection-up hook, lazy
        resolve, bearer-created hook) without double-registering.
        """
        import asyncio

        if getattr(bearer, "_btp_notif_wired", False):
            return
        peer_bytes = bytes(peer)[:6]
        type_byte = int(addr_type) & 0xFF

        def _do_emit(notif_type: int, char_handle: int, value: bytes):
            if self._tester is None:
                return
            payload = bytearray()
            payload.append(type_byte)
            payload.extend(peer_bytes)
            payload.append(notif_type & 0xFF)
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

        bearer._btp_emit = _do_emit

        def _emit(notif_type: int, char_handle: int, value: bytes):
            enc = bool(is_encrypted(conn_handle)) if callable(is_encrypted) else True
            pend = bool(encrypt_pending(conn_handle)) if callable(encrypt_pending) else False
            logger.debug("GATT notif rx handle=0x%04x type=%d enc=%s pend=%s -> %s",
                         char_handle, notif_type, enc, pend,
                         "forward" if (enc or not pend) else "DROP(pre-encrypt)")
            if enc or not pend:
                _do_emit(notif_type, char_handle, value)
            # else: DROP. On a bonded reconnect that is about to (re-)encrypt, an
            # indication/notification PTS sends *before* encryption completes must
            # be confirmed at the ATT layer but NEVER reported to the Upper Tester
            # (GAP.TS Table 4.20 step 9A.4/9B.4). PTS then sends a *second* IND
            # after encryption (step 10) which IS reported (step 12). Holding and
            # flushing the first one would leak it into the WID-236 "must not
            # report" check → FAIL. So drop, don't queue.

        bearer.set_notification_handler(lambda h, v: _emit(1, h, v))
        bearer.set_indication_handler(lambda h, v: _emit(2, h, v))
        bearer._btp_notif_wired = True
