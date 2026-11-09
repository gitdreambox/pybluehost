"""GATT Server and Client — attribute database, service definitions, request handling."""
from __future__ import annotations

import asyncio
import logging
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
    ATT_Read_Blob_Request, ATT_Read_Blob_Response,
    ATT_Read_Multiple_Request, ATT_Read_Multiple_Response,
    ATT_Read_Multiple_Variable_Request, ATT_Read_Multiple_Variable_Response,
    ATT_Write_Request, ATT_Write_Response, ATT_Write_Command,
    ATT_Prepare_Write_Request, ATT_Prepare_Write_Response,
    ATT_Execute_Write_Request, ATT_Execute_Write_Response,
    ATT_Read_By_Type_Request, ATT_Read_By_Type_Response,
    ATT_Read_By_Group_Type_Request, ATT_Read_By_Group_Type_Response,
    ATT_Find_Information_Request, ATT_Find_Information_Response,
    ATT_Find_By_Type_Value_Request, ATT_Find_By_Type_Value_Response,
    ATT_Handle_Value_Notification, ATT_Handle_Value_Indication,
    decode_att_pdu,
)
from pybluehost.l2cap.constants import CID_ATT


logger = logging.getLogger(__name__)

# Sentinel returned by the robust-caching gate for ATT commands that must be
# silently ignored (no response at all) — handle_request maps it to None.
_IGNORED_SENTINEL = ATTPdu()


def _log_service_discovery_complete(*, handle: int, num_services: int) -> None:
    """Log completion of GATT primary-service discovery on a connection."""
    logger.info("GATT discovered %d services on handle=0x%04X", num_services, handle)


def _log_cccd_subscribed(*, handle: int, char_handle: int, char_name: str | None) -> None:
    """Log a successful CCCD subscription for a characteristic."""
    suffix = f" ({char_name})" if char_name else ""
    logger.info("GATT subscribed to handle=0x%04X%s via CCCD", char_handle, suffix)


def _log_notification_received(*, handle: int, char_handle: int, length: int) -> None:
    """Log inbound Handle_Value_Notification received on a connection."""
    logger.debug("GATT notification handle=0x%04X char=0x%04X len=%d", handle, char_handle, length)


# GATT UUIDs
UUID_PRIMARY_SERVICE = UUID16(0x2800)
UUID_SECONDARY_SERVICE = UUID16(0x2801)
UUID_INCLUDE = UUID16(0x2802)
UUID_CHARACTERISTIC = UUID16(0x2803)
UUID_CCCD = UUID16(0x2902)  # Client Characteristic Configuration Descriptor
UUID_SERVICE_CHANGED = UUID16(0x2A05)


def _uuid_le_bytes(uuid: UUID16 | UUID128) -> bytes:
    """UUID -> little-endian on-air bytes.

    ``UUID16.to_bytes()`` is already LE, but ``UUID128`` stores big-endian
    internally (RFC 4122 string order), so a 128-bit UUID must be reversed for
    the ATT wire (GATT/SR/GAR/BV-03 declaration / Find Information).
    """
    return uuid.to_bytes_le()


class Permissions(IntFlag):
    READABLE = 0x01
    WRITABLE = 0x02
    READABLE_ENCRYPTED = 0x04
    WRITABLE_ENCRYPTED = 0x08


# auto-pts BTP attribute-permission bits (doc/btp_gatt.txt). The BTP GATT
# service stores the raw byte in ``Attribute.permissions``; the low nibble
# coincides with ``Permissions`` above, and the high nibble carries the
# authentication/authorization requirements the ATT server must enforce.
PERM_READ = 0x01
PERM_WRITE = 0x02
PERM_READ_ENC = 0x04       # read requires an encrypted link
PERM_WRITE_ENC = 0x08      # write requires an encrypted link
PERM_READ_AUTHN = 0x10     # read requires authentication (MITM)
PERM_WRITE_AUTHN = 0x20    # write requires authentication (MITM)
PERM_READ_AUTHZ = 0x40     # read requires authorization
PERM_WRITE_AUTHZ = 0x80    # write requires authorization

# Union masks: "is this attribute readable/writable at ANY security level?".
# The four level bits are mutually exclusive in practice, so a security-gated
# attribute sets exactly one of them (and NOT the plain bit).
_PERM_READ_ANY = PERM_READ | PERM_READ_ENC | PERM_READ_AUTHN | PERM_READ_AUTHZ
_PERM_WRITE_ANY = PERM_WRITE | PERM_WRITE_ENC | PERM_WRITE_AUTHN | PERM_WRITE_AUTHZ

# ATT error codes (Core Spec Vol 3, Part F, §3.4.1.1 Table 3.4).
ATT_ERR_INVALID_HANDLE = 0x01
ATT_ERR_READ_NOT_PERMITTED = 0x02
ATT_ERR_WRITE_NOT_PERMITTED = 0x03
ATT_ERR_INSUFFICIENT_AUTHENTICATION = 0x05
ATT_ERR_REQUEST_NOT_SUPPORTED = 0x06
ATT_ERR_INVALID_OFFSET = 0x07
ATT_ERR_INSUFFICIENT_AUTHORIZATION = 0x08
ATT_ERR_ATTRIBUTE_NOT_FOUND = 0x0A
ATT_ERR_INSUFFICIENT_ENC_KEY_SIZE = 0x0C
ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH = 0x0D
ATT_ERR_INSUFFICIENT_ENCRYPTION = 0x0F
ATT_ERR_VALUE_NOT_ALLOWED = 0x13


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
    # Required encryption key size (bytes) when the attribute's permissions
    # include an ENC bit; 0 = no specific requirement. Mirrors the BTP
    # gatts_set_enc_key_size value so the server can return
    # Insufficient Encryption Key Size (0x0C).
    enc_key_size: int = 0
    # Largest value this attribute accepts. None = no length enforcement.
    # The PTS GATT/SR db declares fixed-size characteristics (8 bytes), and
    # PTS checks that an over-long write is rejected (GAW/BI-32/33/39/40).
    max_length: int | None = None


@dataclass
class _ConnSecurity:
    """Per-connection link security state for ATT permission enforcement."""

    encrypted: bool = False
    authenticated: bool = False
    key_size: int = 0


@dataclass
class _RobustClientState:
    """Per-connection Robust Caching state (Core Vol 3 Part G §2.5.2.1)."""

    csf: bytes = b"\x00"
    change_unaware: bool = False
    # Bearer CIDs on which the resync trigger (0x12 or a Database Hash read)
    # has already fired — "Database Out Of Sync sent once" is per-BEARER
    # (Figure 2.7). The fixed channel contributes CID_ATT at most.
    synced_pending: set[int] = field(default_factory=set)

    @property
    def robust_caching_enabled(self) -> bool:
        return bool(self.csf[:1]) and bool(self.csf[0] & 0x01)

    def mark_database_changed(self) -> None:
        self.change_unaware = True
        self.synced_pending.clear()


class AttributeDatabase:
    """Linear attribute database with auto-incrementing handles."""

    def __init__(self) -> None:
        self._attrs: list[Attribute] = []
        self._next_handle: int = 0x0001

    # -- Database Hash (Core Vol 3 Part G §7.3.1, RFC-4493 AES-CMAC) ----------

    # Attribute types whose Handle+Type+Value feed the hash (§7.3.1).
    _HASH_TYPES_WITH_VALUE = {0x2800, 0x2801, 0x2802, 0x2803, 0x2900}
    # Attribute types whose Handle+Type only feed the hash.
    _HASH_TYPES_HANDLE_TYPE_ONLY = {0x2901, 0x2902, 0x2903, 0x2904, 0x2905}

    def database_hash(self) -> bytes:
        """Compute the Database Hash characteristic value.

        AES-CMAC with the all-zero key over the concatenation (ascending
        handle order, little-endian fields) of:
        - Handle+Type+Value for Primary/Secondary Service, Included Service,
          Characteristic and Characteristic Extended Properties declarations;
        - Handle+Type for the descriptor declarations (User Description, CCC,
          SCC, Presentation Format, Aggregate Format);
        - nothing for any other attribute (characteristic VALUES, the Database
          Hash value itself, CSF value...).
        """
        m = bytearray()
        for attr in sorted(self._attrs, key=lambda a: a.handle):
            t = attr.type_uuid.value if isinstance(attr.type_uuid, UUID16) else None
            if t in self._HASH_TYPES_WITH_VALUE:
                m += attr.handle.to_bytes(2, "little")
                m += t.to_bytes(2, "little")
                m += attr.value
            elif t in self._HASH_TYPES_HANDLE_TYPE_ONLY:
                m += attr.handle.to_bytes(2, "little")
                m += t.to_bytes(2, "little")
        from cryptography.hazmat.primitives.ciphers import algorithms
        from cryptography.hazmat.primitives.cmac import CMAC
        cmac = CMAC(algorithms.AES(bytes(16)))
        cmac.update(bytes(m))
        digest = cmac.finalize()
        logger.debug("database hash %s over %d bytes", digest.hex().upper(), len(m))
        return digest

    def database_hash_value(self) -> bytes:
        """The value served by the Database Hash characteristic (0x2B2A).

        The AES-CMAC output is big-endian, but a multi-octet characteristic
        value is little-endian unless stated otherwise (Core Vol 3 Part F
        §3.3.1) and PTS compares in that order — zephyr's ``db_hash_gen``
        swaps for exactly this reason ("PTS expects hash to be in little
        endianness as well ... so we have to swap"). ``database_hash()``
        keeps the raw CMAC so the Appendix B vector can be compared with the
        spec as published.
        """
        return self.database_hash()[::-1]

    def add(self, type_uuid: UUID16 | UUID128, permissions: Permissions, value: bytes = b"", enc_key_size: int = 0, max_length: int | None = None) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self._attrs.append(Attribute(handle=handle, type_uuid=type_uuid, permissions=permissions, value=value, enc_key_size=enc_key_size, max_length=max_length))
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
        # Any service declaration (0x2800 OR 0x2801) ends the current group per
        # the ATT grouping rules (Vol 3 Part F 3.2.2) — not just another
        # declaration of the SAME type. Matching only the same type reported a
        # lone secondary service as spanning the whole database.
        svc_types = (UUID16(0x2800).to_bytes(), UUID16(0x2801).to_bytes())
        groups = []
        for i, attr in enumerate(self._attrs):
            if start <= attr.handle <= end and attr.type_uuid.to_bytes() == type_bytes:
                # Find end of this group (next service declaration - 1, or last handle)
                end_handle = self._attrs[-1].handle  # default: last attr
                for j in range(i + 1, len(self._attrs)):
                    if self._attrs[j].type_uuid.to_bytes() in svc_types:
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
    enc_key_size: int = 0
    max_length: int | None = None


@dataclass
class CharacteristicDefinition:
    uuid: UUID16 | UUID128
    properties: CharProperties
    permissions: Permissions
    value: bytes = b""
    descriptors: list[DescriptorDefinition] = field(default_factory=list)
    enc_key_size: int = 0
    max_length: int | None = None


@dataclass
class IncludeDefinition:
    """A GATT Include declaration (type 0x2802) referencing another service.

    ``start_handle`` / ``end_handle`` are handles in the database being built:
    the included service must already have been added, and the handles are its
    real (already assigned) range. ``uuid`` is the included service's UUID as
    it appears in the declaration value.
    """

    start_handle: int
    end_handle: int
    uuid: UUID16 | UUID128


@dataclass
class ServiceDefinition:
    uuid: UUID16 | UUID128
    characteristics: list[CharacteristicDefinition] = field(default_factory=list)
    is_primary: bool = True
    # Include declarations are emitted immediately after the service
    # declaration, before any characteristic (auto-pts' GATT/SR init_server adds
    # one this way, and the GATT/SR handle layout is written against it).
    includes: list[IncludeDefinition] = field(default_factory=list)


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
        self._indication_callback: Callable | None = None
        self._multiple_notification_callback: Callable | None = None
        self._read_handlers: dict[int, Callable[[], bytes | Awaitable[bytes]]] = {}
        self._write_handlers: dict[int, Callable[[bytes], object | Awaitable[object]]] = {}
        # conn_handle -> set of value_handles with notifications enabled
        self._notifications_enabled: dict[int, set[int]] = {}
        # conn_handle -> set of value_handles with indications enabled (CCCD
        # bit 0x0002). Tracked separately from notifications so the Service
        # Changed characteristic (indicate-only) is driven correctly.
        self._indications_enabled: dict[int, set[int]] = {}
        # (conn_handle, bearer_cid) -> negotiated ATT MTU. The fixed ATT
        # channel's bearer key is CID_ATT (default 23 until Exchange MTU); an
        # EATT bearer's MTU is its L2CAP channel MTU, set at attach time by
        # add_eatt_bearer (no Exchange MTU on EATT — GATT.TS §4.2.5).
        # Responses must be truncated to this or the peer (which may never
        # exchange MTU, e.g. PTS GATT/SR reads) treats oversized PDUs as a
        # protocol violation and stalls.
        self._conn_mtu: dict[tuple[int, int], int] = {}
        # conn_handle -> set of EATT bearer CIDs attached to this connection
        # (channels on the fixed EATT SPSM 0x0027). Registered by the stack at
        # bearer attach time for stack wiring, is_eatt_bearer queries, and
        # cleanup on disconnect. Exchange MTU rejection on EATT is based on
        # bearer_cid != CID_ATT, NOT this registry.
        self._eatt_bearers: dict[int, set[int]] = {}
        # conn_handle -> link security state. Default (absent) = unencrypted /
        # unauthenticated / key_size 0, which is exactly what the PTS GATT/SR
        # error-handling (BI) cases exercise: they connect without pairing.
        self._conn_security: dict[int, _ConnSecurity] = {}
        # conn_handle -> queued Prepare Write entries awaiting Execute Write.
        self._prepare_queue: dict[int, list[tuple[int, int, bytes]]] = {}
        # Robust Caching state per connection (Core Vol 3 Part G §2.5.2.1):
        # csf = this client's Client Supported Features value; change_unaware
        # = the db changed since the client last synced; synced_pending = a
        # resync trigger already fired (0x12 delivered or Database Hash read)
        # so the NEXT ATT request transitions the client to change-aware.
        self._robust: dict[int, "_RobustClientState"] = {}
        # conn_handle -> (start, end) of a Service Changed indication that could
        # not be delivered because the client was disconnected when the database
        # changed. Flushed on the client's first ATT request after it reconnects
        # (GAS/BV-01, BV-07 — the SC indication resends after a bonded reconnect).
        self._service_changed_pending: dict[int, tuple[int, int]] = {}

    _DEFAULT_ATT_MTU = 23
    _SERVER_RX_MTU = 512

    def _att_mtu(self, conn_handle: int, bearer_cid: int = CID_ATT) -> int:
        return self._conn_mtu.get((conn_handle, bearer_cid), self._DEFAULT_ATT_MTU)

    # -- EATT bearers (Enhanced ATT over Enhanced Credit-Based channels) ------

    def add_eatt_bearer(self, conn_handle: int, bearer_cid: int, *, mtu: int) -> None:
        """Register an EATT bearer on a connection. The bearer's ATT_MTU is the
        channel's negotiated L2CAP MTU — there is no Exchange MTU on EATT
        (GATT.TS §4.2.5). Re-registering the same CID resets its MTU (CID
        reuse must not inherit a stale value)."""
        self._eatt_bearers.setdefault(conn_handle, set()).add(bearer_cid)
        self._conn_mtu[(conn_handle, bearer_cid)] = min(mtu, self._SERVER_RX_MTU)

    def remove_eatt_bearer(self, conn_handle: int, bearer_cid: int) -> None:
        bearers = self._eatt_bearers.get(conn_handle)
        if bearers is not None:
            bearers.discard(bearer_cid)
            if not bearers:
                del self._eatt_bearers[conn_handle]
        self._conn_mtu.pop((conn_handle, bearer_cid), None)
        state = self._robust.get(conn_handle)
        if state is not None:
            state.synced_pending.discard(bearer_cid)

    def is_eatt_bearer(self, conn_handle: int, bearer_cid: int) -> bool:
        return bearer_cid in self._eatt_bearers.get(conn_handle, set())

    def set_connection_security(
        self, conn_handle: int, *, encrypted: bool, authenticated: bool = False,
        key_size: int = 0,
    ) -> None:
        """Record the link security state for a connection (called by the stack
        on encryption-change / pairing-complete). Used to enforce ENC/AUTHN/
        AUTHZ permission bits and return the correct ATT error code."""
        self._conn_security[conn_handle] = _ConnSecurity(
            encrypted=encrypted, authenticated=authenticated, key_size=key_size)

    def _security(self, conn_handle: int) -> "_ConnSecurity":
        return self._conn_security.get(conn_handle, _ConnSecurity())

    def remove_connection(self, conn_handle: int, *, bonded: bool = True) -> None:
        """Drop per-connection state when a link closes.

        ``_indications_enabled`` (and ``_robust``) are deliberately kept: a
        bonded client's Service Changed CCCD subscription and change-unaware
        flag survive the disconnect so the IUT can resend the indication on
        reconnect (GAS/BV-01, BV-07). The controller reuses the same LE
        connection handle, so the per-handle entries are the client's own.
        The EATT bearer registry (``_eatt_bearers``) and all
        ``(conn_handle, *)`` MTU entries are cleared, as is all other
        per-connection ATT state below.

        ``bonded=False`` additionally resets the CCCD values this client wrote:
        Core Vol 3 Part G §3.3.3.3 only persists a client's CCCD across
        connections when the client is bonded, and GATT.TS GAN/BV-01 step 5A
        reads the CCCD after reconnect and expects 0x0000. Service Changed is
        not exempt — GAI/BV-01 step 7A.1 reads *its* CCCD and also expects
        0x0000; the robust-caching cases that keep SC state across a reconnect
        (GAS/BV-01, BV-07) are bonded and never take this branch."""
        if not bonded:
            self.reset_unbonded_cccd(
                conn_handle, self.connection_cccd_handles(conn_handle))
        for key in [k for k in self._conn_mtu if k[0] == conn_handle]:
            del self._conn_mtu[key]
        self._eatt_bearers.pop(conn_handle, None)
        self._conn_security.pop(conn_handle, None)
        self._prepare_queue.pop(conn_handle, None)
        self._notifications_enabled.pop(conn_handle, None)
        # The "Database Out Of Sync sent once" marker is per-BEARER (Figure 2.7):
        # a new connection must get its own 0x12 again. change_unaware itself
        # persists (the client never resynced), but synced_pending resets so the
        # next connection's first read is DoS again (GAS/BV-07 step 9).
        state = self._robust.get(conn_handle)
        if state is not None:
            state.synced_pending.clear()

    def connection_cccd_handles(self, conn_handle: int) -> list[int]:
        """Value handles this connection enabled notification/indication on."""
        handles = set(self._notifications_enabled.get(conn_handle, set()))
        handles |= set(self._indications_enabled.get(conn_handle, set()))
        return sorted(handles)

    def reset_unbonded_cccd(self, conn_handle: int, value_handles: list[int]) -> None:
        """Reset the stored CCCD values a non-bonded client wrote, and forget
        its indication subscriptions.

        Core Vol 3 Part G §3.3.3.3: a client's CCCD state survives a
        disconnect only while the client is bonded.  There is deliberately
        **no** exemption for the Service Changed characteristic here — GATT.TS
        GATT/SR/GAI/BV-01-C subscribes to Service Changed, reconnects without
        bonding and requires the CCCD to read 0x0000 (step 7A.1).  The
        robust-caching cases that do need Service Changed state across a
        reconnect (GAS/BV-01, GAS/BV-07) are bonded, so they never reach this
        method.

        The connection handle is reused by the controller, so stale
        subscriptions/values from the departed client would otherwise leak into
        the next link. ``value_handles`` is a snapshot taken with
        ``connection_cccd_handles`` — the stack resolves bond status
        asynchronously after the disconnect, by which time
        ``_notifications_enabled`` for the connection is already gone."""
        logger.debug("CCCD reset: value_handles=%s", [hex(h) for h in value_handles])
        for value_handle in value_handles:
            cccd = self.db.get(value_handle + 1)
            if cccd is None or cccd.type_uuid.to_bytes() != UUID_CCCD.to_bytes():
                logger.debug(
                    "CCCD reset: value_handle=0x%04X has no CCCD at 0x%04X (attr=%s)",
                    value_handle, value_handle + 1,
                    "missing" if cccd is None else f"type=0x{cccd.type_uuid.value:04X}")
                continue
            logger.debug(
                "CCCD reset: handle=0x%04X %s -> 0000",
                value_handle + 1, cccd.value.hex().upper())
            cccd.value = b"\x00\x00"
        self._indications_enabled.pop(conn_handle, None)
        # The client is no longer subscribed, so a Service Changed indication
        # deferred for it must not be flushed on the next connection.
        self._service_changed_pending.pop(conn_handle, None)

    def _read_error(self, attr: Attribute, sec: "_ConnSecurity") -> int | None:
        """Return the ATT error code for reading `attr` under link `sec`, or None.

        BTP/zephyr encode the read *security level* as independent bits
        (PERM_READ / PERM_READ_ENC / PERM_READ_AUTHN / PERM_READ_AUTHZ); a
        security-gated attribute does NOT set the plain PERM_READ bit, so the
        "read permitted" test must accept ANY read-level bit, then the gate
        below picks the exact error code (0x05/0x08/0x0F/0x0C). Only when no
        read-level bit is set at all is read genuinely not permitted (0x02).
        """
        perms = int(attr.permissions)
        if not (perms & _PERM_READ_ANY):
            return ATT_ERR_READ_NOT_PERMITTED
        if (perms & PERM_READ_AUTHN) and not sec.authenticated:
            return ATT_ERR_INSUFFICIENT_AUTHENTICATION
        if (perms & PERM_READ_AUTHZ) and not sec.authenticated:
            return ATT_ERR_INSUFFICIENT_AUTHORIZATION
        if perms & PERM_READ_ENC:
            if not sec.encrypted:
                # GAP Vol 3 Part C §10.3: an *unpaired* link must be told to PAIR
                # (Insufficient Authentication 0x05) so the central initiates
                # pairing; a bonded/authenticated link only needs to encrypt
                # (Insufficient Encryption 0x0F). Returning 0x0F to an unbonded
                # central leaves it with no LTK to encrypt → it gives up and
                # disconnects (PTS GAP/SEC/AUT/BV-11 INDCSV).
                if not sec.authenticated:
                    return ATT_ERR_INSUFFICIENT_AUTHENTICATION
                return ATT_ERR_INSUFFICIENT_ENCRYPTION
            if attr.enc_key_size and sec.key_size < attr.enc_key_size:
                return ATT_ERR_INSUFFICIENT_ENC_KEY_SIZE
        return None

    def _write_error(self, attr: Attribute, sec: "_ConnSecurity") -> int | None:
        """Return the ATT error code for writing `attr` under link `sec`, or None.

        Mirrors :meth:`_read_error`: any write-level bit means writable, and the
        gate selects 0x05/0x08/0x0F/0x0C; only no write-level bit at all yields
        0x03 (Write Not Permitted).
        """
        perms = int(attr.permissions)
        if not (perms & _PERM_WRITE_ANY):
            return ATT_ERR_WRITE_NOT_PERMITTED
        if (perms & PERM_WRITE_AUTHN) and not sec.authenticated:
            return ATT_ERR_INSUFFICIENT_AUTHENTICATION
        if (perms & PERM_WRITE_AUTHZ) and not sec.authenticated:
            return ATT_ERR_INSUFFICIENT_AUTHORIZATION
        if perms & PERM_WRITE_ENC:
            if not sec.encrypted:
                # Mirror of _read_error: unpaired -> 0x05 (pair), bonded -> 0x0F
                # (encrypt). See _read_error for the GAP §10.3 rationale.
                if not sec.authenticated:
                    return ATT_ERR_INSUFFICIENT_AUTHENTICATION
                return ATT_ERR_INSUFFICIENT_ENCRYPTION
            if attr.enc_key_size and sec.key_size < attr.enc_key_size:
                return ATT_ERR_INSUFFICIENT_ENC_KEY_SIZE
        return None

    def add_service(self, svc: ServiceDefinition) -> ServiceHandles:
        """Add a service to the attribute database, returning handle info."""
        svc_uuid = UUID_PRIMARY_SERVICE if svc.is_primary else UUID_SECONDARY_SERVICE
        svc_value = _uuid_le_bytes(svc.uuid)
        svc_handle = self.db.add(type_uuid=svc_uuid, permissions=Permissions.READABLE, value=svc_value)

        # Include declarations (0x2802) come first, per GATT and per the
        # reference db the GATT/SR handle layout follows. Value =
        # start_handle(2 LE) + end_handle(2 LE) + service UUID (LE).
        for inc in svc.includes:
            self.db.add(
                type_uuid=UUID_INCLUDE,
                permissions=Permissions.READABLE,
                value=struct.pack("<HH", inc.start_handle, inc.end_handle)
                + _uuid_le_bytes(inc.uuid),
            )

        char_handles_list = []
        for char_def in svc.characteristics:
            # Characteristic Declaration (0x2803)
            # Value: properties(1) + value_handle(2 LE) + uuid(2 or 16, LE)
            value_handle_placeholder = self.db._next_handle + 1
            char_decl_value = struct.pack("<BH", int(char_def.properties), value_handle_placeholder) + _uuid_le_bytes(char_def.uuid)
            decl_handle = self.db.add(type_uuid=UUID_CHARACTERISTIC, permissions=Permissions.READABLE, value=char_decl_value)

            # Characteristic Value
            value_handle = self.db.add(type_uuid=char_def.uuid, permissions=char_def.permissions, value=char_def.value, enc_key_size=char_def.enc_key_size, max_length=char_def.max_length)

            # CCCD if NOTIFY or INDICATE — but only if the caller didn't already
            # supply one in `descriptors`. The PTS BTP init_server adds the CCC
            # explicitly via ADD_DESCRIPTOR; auto-adding a second one here would
            # duplicate it and shift every subsequent handle off the zephyr
            # reference db the PTS GATT/SR tests are written against.
            cccd_handle = None
            has_explicit_ccc = any(
                d.uuid.to_bytes() == UUID_CCCD.to_bytes() for d in char_def.descriptors
            )
            if (char_def.properties & (CharProperties.NOTIFY | CharProperties.INDICATE)) and not has_explicit_ccc:
                cccd_handle = self.db.add(
                    type_uuid=UUID_CCCD,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                    value=b"\x00\x00",
                )

            # Additional descriptors
            desc_handles = []
            for desc in char_def.descriptors:
                dh = self.db.add(type_uuid=desc.uuid, permissions=desc.permissions, value=desc.value, enc_key_size=desc.enc_key_size, max_length=desc.max_length)
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

    async def handle_request(
        self, conn_handle: int, pdu: ATTPdu, *, bearer_cid: int = CID_ATT
    ) -> ATTPdu | None:
        """Handle an incoming ATT PDU, returning the response PDU — or ``None``
        for PDUs that must not be answered (Write Command / Signed Write
        Command). ``bearer_cid`` identifies the ATT bearer the PDU arrived on
        (CID_ATT for the fixed channel, the channel CID for an EATT bearer)."""
        logger.debug(
            "ATT RX conn=0x%04X %s handle=0x%04X len=%d",
            conn_handle, type(pdu).__name__,
            getattr(pdu, "attribute_handle", 0) or 0,
            len(getattr(pdu, "attribute_value", b"")
                or getattr(pdu, "part_attribute_value", b"") or b""),
        )
        # Deliver a deferred Service Changed indication before processing the
        # request: on reconnect the client may read before the connection-open
        # flush task has run (it is scheduled asynchronously), so flush here
        # synchronously. Idempotent — the pending entry is popped.
        await self.on_connection_opened(conn_handle)
        self._refresh_database_hash()
        gated = self._robust_caching_gate(conn_handle, pdu, bearer_cid)
        if gated is _IGNORED_SENTINEL:
            return None
        if gated is not None:
            return gated
        csf = self._maybe_csf_pdu(conn_handle, pdu)
        if csf is _IGNORED_SENTINEL:
            return None
        if csf is not None:
            return csf
        return await self._dispatch(conn_handle, pdu, bearer_cid)

    # -- Robust Caching (Core Vol 3 Part G §2.5.2.1) ---------------------------

    def mark_database_changed(self) -> None:
        """Database definitions changed: every connected client becomes
        change-unaware (PTS GAS/BV-05/06; called by the BTP CHANGE_DATABASE
        handler)."""
        logger.debug(
            "GATT mark_database_changed robust=%s sc_subscribed=%s",
            list(self._robust.keys()),
            list(self._indications_enabled.keys()),
        )
        for state in self._robust.values():
            state.mark_database_changed()

    def on_confirmation(self, conn_handle: int) -> None:
        """Handle an ATT_Handle_Value_Confirmation from a client.

        A Service Changed indication is the resync trigger (Core Vol 3 Part G
        §2.5.2.1): once the client confirms it, it is change-aware again, so
        the next read returns the value rather than Database Out Of Sync
        (GAS/BV-06 step 7). Wired from the ATT channel mux, which routes the
        0x1E opcode to the server when it owns the connection.
        """
        state = self._robust.get(conn_handle)
        if state is not None:
            logger.debug("GATT on_confirmation conn=0x%04X clearing change-unaware", conn_handle)
            state.change_unaware = False
            state.synced_pending.clear()

    def _csf_value_handle(self) -> int | None:
        for attr in self.db._attrs:
            if isinstance(attr.type_uuid, UUID16) and attr.type_uuid.value == 0x2B29:
                return attr.handle
        return None

    def _maybe_csf_pdu(self, conn_handle: int, pdu: ATTPdu) -> ATTPdu | None:
        """Per-connection Client Supported Features handling (GAS/BV-03/04).

        The CSF value is per-client: reads return THIS connection's instance
        (default zero) and writes store into it, masked to the defined bits
        (octet 0: robust caching | EATT bearer | multiple handle value
        notifications = 0x07; RFU bits read back as 0). Returns the response
        PDU, _IGNORED_SENTINEL for a Write Command, or None when the PDU does
        not target the CSF value.
        """
        csf_handle = self._csf_value_handle()
        if csf_handle is None:
            return None
        state = self._robust.setdefault(conn_handle, _RobustClientState())

        if isinstance(pdu, ATT_Read_Request) and pdu.attribute_handle == csf_handle:
            return ATT_Read_Response(attribute_value=state.csf)
        if isinstance(pdu, ATT_Read_Blob_Request) and pdu.attribute_handle == csf_handle:
            return ATT_Read_Blob_Response(
                part_attribute_value=state.csf[pdu.value_offset:])
        if isinstance(pdu, (ATT_Write_Request, ATT_Write_Command)) and pdu.attribute_handle == csf_handle:
            # Robust Caching cannot be disabled while connected (Core Vol 3 Part G
            # §2.5.2.1): a write clearing the RC bit (1 -> 0) is rejected with
            # Value Not Allowed and the value is left unchanged (GAS/BV-05 step 11,
            # BV-07 step 7). Write Command carries no response, so it is just
            # ignored the same way.
            was_enabled = state.robust_caching_enabled
            wants_disable = bool(pdu.attribute_value) and not (pdu.attribute_value[0] & 0x01)
            if was_enabled and wants_disable:
                if isinstance(pdu, ATT_Write_Request):
                    return ATT_Error_Response(
                        request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                        attribute_handle_in_error=csf_handle,
                        error_code=ATT_ERR_VALUE_NOT_ALLOWED,
                    )
                return _IGNORED_SENTINEL
            masked = bytes(pdu.attribute_value)
            if masked:
                masked = bytes([masked[0] & 0x07]) + bytes(masked[1:])
            state.csf = masked or b"\x00"
            if isinstance(pdu, ATT_Write_Request):
                return ATT_Write_Response()
            return _IGNORED_SENTINEL
        return None

    def _robust_caching_gate(
        self, conn_handle: int, pdu: ATTPdu, bearer_cid: int
    ) -> ATTPdu | None:
        """Return an ATT_Error_Response to send instead of processing ``pdu``,
        None to continue normal dispatch, or _IGNORED_SENTINEL when the PDU is
        a command that must be silently dropped.

        Rules (§2.5.2.1): a change-unaware client that enabled Robust Caching
        gets Database Out Of Sync (0x12) for handle-based ATT requests — sent
        ONCE per bearer; the next request then proceeds (Figure 2.7). ATT
        commands are ignored. READ_BY_TYPE is exempt when it is discovery
        (type Include/Characteristic) or spans the full 0x0001-0xFFFF range —
        the latter being the Database-Hash resync read.
        """
        state = self._robust.get(conn_handle)
        if state is None or not state.change_unaware or not state.robust_caching_enabled:
            return None

        logger.debug(
            "GATT robust gate conn=0x%04X pdu=%s unaware=%s synced_pending=%s rc=%s",
            conn_handle, type(pdu).__name__, state.change_unaware,
            state.synced_pending, state.robust_caching_enabled,
        )

        if isinstance(pdu, ATT_Read_By_Type_Request):
            is_discovery = pdu.attribute_type in (
                UUID16(0x2802).to_bytes(), UUID16(0x2803).to_bytes())
            full_range = (pdu.starting_handle, pdu.ending_handle) == (0x0001, 0xFFFF)
            if is_discovery or full_range:
                if pdu.attribute_type == UUID16(0x2B2A).to_bytes() and full_range:
                    # Database Hash read: the resync trigger — the client's
                    # NEXT request transitions it to change-aware.
                    state.synced_pending.add(bearer_cid)
                return None  # process normally
            return self._database_out_of_sync(pdu, state, bearer_cid)

        # ATT commands (no response expected) from an unaware client are
        # silently ignored (§2.5.2.1 / Figure 2.6).
        if isinstance(pdu, (ATT_Write_Command,)):
            return _IGNORED_SENTINEL

        # Any other handle-based request.
        if bearer_cid in state.synced_pending:
            state.change_unaware = False
            state.synced_pending.discard(bearer_cid)
            return None  # resync completed — process normally
        return self._database_out_of_sync(pdu, state, bearer_cid)

    def _database_out_of_sync(
        self, pdu: ATTPdu, state: _RobustClientState, bearer_cid: int
    ) -> ATT_Error_Response:
        opcode = getattr(pdu, "_opcode_value", None)
        if opcode is None:
            try:
                opcode = pdu.to_bytes()[0]
            except Exception:
                opcode = 0
        state.synced_pending.add(bearer_cid)  # the 0x12 itself is the resync trigger
        return ATT_Error_Response(
            request_opcode_in_error=opcode,
            attribute_handle_in_error=getattr(pdu, "attribute_handle", 0) or 0,
            error_code=0x12,  # Database Out Of Sync
        )

    def _refresh_database_hash(self) -> None:
        """Keep the Database Hash characteristic (0x2B2A) value current.

        The hash is derived from the whole attribute table (Core Vol 3 Part G
        §7.3.1) and must reflect db changes immediately: PTS GAS/BV-02 changes
        the db mid-test (BTP CHANGE_DATABASE) and re-reads the hash expecting a
        new value. Refreshing on every request is cheap (CMAC over a small
        table) and covers Read / Read By Type / Read Blob uniformly. The hash
        attribute's own value does not feed the hash, so this is stable.
        """
        for attr in self.db._attrs:
            if isinstance(attr.type_uuid, UUID16) and attr.type_uuid.value == 0x2B2A:
                # Little-endian on the wire (see database_hash_value).
                attr.value = self.db.database_hash_value()
                return

    async def _dispatch(self, conn_handle: int, pdu: ATTPdu, bearer_cid: int) -> ATTPdu | None:
        if isinstance(pdu, ATT_Read_Request):
            return await self._handle_read(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Blob_Request):
            return await self._handle_read_blob(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Multiple_Request):
            return await self._handle_read_multiple(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_Multiple_Variable_Request):
            return self._handle_read_multiple_variable(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Write_Request):
            return await self._handle_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Write_Command):
            return await self._handle_write_command(conn_handle, pdu)
        elif isinstance(pdu, ATT_Prepare_Write_Request):
            return await self._handle_prepare_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Execute_Write_Request):
            return await self._handle_execute_write(conn_handle, pdu)
        elif isinstance(pdu, ATT_Exchange_MTU_Request):
            if bearer_cid != CID_ATT:
                # Exchange MTU is not applicable over the Enhanced ATT bearer
                # (the MTU comes from L2CAP channel configuration) — GATT.TS
                # §4.2.5; the rejection is GATT/SR/GAC/BI-01's pass criterion.
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.EXCHANGE_MTU_REQUEST,
                    attribute_handle_in_error=0x0000,
                    error_code=0x06,  # Request Not Supported
                )
            # Negotiated ATT MTU = min(client rx, our rx); remember it per
            # bearer so list responses are truncated to fit.
            self._conn_mtu[(conn_handle, bearer_cid)] = min(pdu.client_rx_mtu, self._SERVER_RX_MTU)
            logger.debug("GATT exchange_mtu conn=0x%04X bearer=0x%04X client_rx=%d negotiated=%d",
                         conn_handle, bearer_cid, pdu.client_rx_mtu,
                         self._conn_mtu[(conn_handle, bearer_cid)])
            return ATT_Exchange_MTU_Response(server_rx_mtu=self._SERVER_RX_MTU)
        elif isinstance(pdu, ATT_Read_By_Group_Type_Request):
            return self._handle_read_by_group_type(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Read_By_Type_Request):
            return self._handle_read_by_type(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Find_Information_Request):
            return self._handle_find_information(conn_handle, pdu, bearer_cid)
        elif isinstance(pdu, ATT_Find_By_Type_Value_Request):
            return self._handle_find_by_type_value(pdu)
        return ATT_Error_Response(
            request_opcode_in_error=0, attribute_handle_in_error=0,
            error_code=0x06,  # Request Not Supported
        )

    async def _handle_read(self, conn_handle: int, pdu: ATT_Read_Request, bearer_cid: int) -> ATTPdu:
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_HANDLE,
            )
        err = self._read_error(attr, self._security(conn_handle))
        if err is not None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=err,
            )
        handler = self._read_handlers.get(pdu.attribute_handle)
        if handler is not None:
            value = handler()
            if asyncio.iscoroutine(value):
                value = await value
            attr.value = value
        # ATT_Read_Response carries value bytes with no length field, so the
        # payload must fit in (ATT_MTU - 1); a longer value requires Read Blob.
        mtu = self._att_mtu(conn_handle, bearer_cid)
        truncated = attr.value[: mtu - 1]
        logger.debug("GATT read handle=0x%04X value_len=%d mtu=%d -> %d value=%s",
                     pdu.attribute_handle, len(attr.value), mtu, len(truncated),
                     truncated.hex().upper())
        return ATT_Read_Response(attribute_value=truncated)

    async def _handle_read_blob(self, conn_handle: int, pdu: ATT_Read_Blob_Request, bearer_cid: int) -> ATTPdu:
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BLOB_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_HANDLE,
            )
        err = self._read_error(attr, self._security(conn_handle))
        if err is not None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BLOB_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=err,
            )
        if pdu.value_offset > len(attr.value):
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BLOB_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_OFFSET,
            )
        handler = self._read_handlers.get(pdu.attribute_handle)
        if handler is not None:
            value = handler()
            if asyncio.iscoroutine(value):
                value = await value
            attr.value = value
        mtu = self._att_mtu(conn_handle, bearer_cid)
        return ATT_Read_Blob_Response(part_attribute_value=attr.value[pdu.value_offset: pdu.value_offset + mtu - 1])

    async def _handle_read_multiple(self, conn_handle: int, pdu: ATT_Read_Multiple_Request, bearer_cid: int) -> ATTPdu:
        # Read Multiple (0x0E): concatenate the values of the requested handles.
        # set_of_handles is raw LE u16 pairs. Per spec every handle must exist
        # and be readable; the first failure produces an Error Response naming
        # that handle.
        handles = [struct.unpack_from("<H", pdu.set_of_handles, i)[0]
                   for i in range(0, len(pdu.set_of_handles) - 1, 2)]
        sec = self._security(conn_handle)
        for handle in handles:
            attr = self.db.get(handle)
            if attr is None:
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.READ_MULTIPLE_REQUEST,
                    attribute_handle_in_error=handle,
                    error_code=ATT_ERR_INVALID_HANDLE,
                )
            err = self._read_error(attr, sec)
            if err is not None:
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.READ_MULTIPLE_REQUEST,
                    attribute_handle_in_error=handle,
                    error_code=err,
                )
        mtu = self._att_mtu(conn_handle, bearer_cid)
        data = b""
        for handle in handles:
            attr = self.db.get(handle)
            handler = self._read_handlers.get(handle)
            if handler is not None:
                value = handler()
                if asyncio.iscoroutine(value):
                    value = await value
                attr.value = value
            if len(data) + len(attr.value) > mtu - 1:
                break
            data += attr.value
        return ATT_Read_Multiple_Response(set_of_values=data)

    def _handle_read_multiple_variable(self, conn_handle: int, pdu: ATT_Read_Multiple_Variable_Request, bearer_cid: int) -> ATTPdu:
        """Read Multiple Variable Length (0x20): return each requested value as a
        (length u8, value) tuple. Unlike fixed Read Multiple (0x0E), each value is
        length-prefixed so values may differ in size; the last one is truncated to
        fit ATT_MTU. Every handle must exist and be readable — the first failure
        yields an Error Response naming that handle (same rule as 0x0E)."""
        handles = [struct.unpack_from("<H", pdu.set_of_handles, i)[0]
                   for i in range(0, len(pdu.set_of_handles) - 1, 2)]
        sec = self._security(conn_handle)
        for handle in handles:
            attr = self.db.get(handle)
            if attr is None:
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.READ_MULTIPLE_VARIABLE_REQUEST,
                    attribute_handle_in_error=handle,
                    error_code=ATT_ERR_INVALID_HANDLE,
                )
            err = self._read_error(attr, sec)
            if err is not None:
                return ATT_Error_Response(
                    request_opcode_in_error=ATTOpcode.READ_MULTIPLE_VARIABLE_REQUEST,
                    attribute_handle_in_error=handle,
                    error_code=err,
                )
        mtu = self._att_mtu(conn_handle, bearer_cid)
        used = 1  # response opcode
        values: list[bytes] = []
        for handle in handles:
            attr = self.db.get(handle)
            # Per-entry budget: 1 length octet + value. Cap a single value at 253
            # (u8 length field) and at whatever MTU budget remains.
            budget = mtu - used - 1
            if budget < 0:
                break
            chunk = attr.value[: min(len(attr.value), budget, 253)]
            values.append(chunk)
            used += 1 + len(chunk)
            if used >= mtu:
                break
        return ATT_Read_Multiple_Variable_Response(values=values)

    async def _handle_write(self, conn_handle: int, pdu: ATT_Write_Request) -> ATTPdu:
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_HANDLE,
            )
        err = self._write_error(attr, self._security(conn_handle))
        if err is not None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=err,
            )
        if self._value_too_long(attr, len(pdu.attribute_value)):
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH,
            )
        await self._apply_write(conn_handle, pdu.attribute_handle, pdu.attribute_value)
        return ATT_Write_Response()

    async def _handle_write_command(self, conn_handle: int, pdu: ATT_Write_Command) -> None:
        """ATT Write Command (0x52, Write Without Response). Commit the value if
        the attribute exists and is writable under the current security level,
        then return ``None`` — a command is never answered, even on error (Core
        Vol 3 Part F §3.4.5). GAP/GAT/BV-05/06 rely on this (PTS writes Device
        Name / Appearance via Write Command then reads back).

        An over-long value is dropped without committing: PTS verifies both that
        no message comes back AND that a later read still returns the old value
        (GAW/BI-39/BI-40).
        """
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return None
        if self._write_error(attr, self._security(conn_handle)) is not None:
            return None
        if self._value_too_long(attr, len(pdu.attribute_value)):
            return None
        await self._apply_write(conn_handle, pdu.attribute_handle, pdu.attribute_value)
        return None

    @staticmethod
    def _value_too_long(attr: Attribute, length: int) -> bool:
        """True when a write of ``length`` bytes exceeds the attribute's
        declared maximum (ATT error 0x0D, Invalid Attribute Value Length)."""
        return attr.max_length is not None and length > attr.max_length

    async def _apply_write(self, conn_handle: int, handle: int, value: bytes) -> None:
        """Commit a characteristic/descriptor value write (shared by Write
        Request and Execute Write) including CCCD subscription bookkeeping."""
        attr = self.db.get(handle)
        if attr is None:
            return
        # Check if this is a CCCD write
        if attr.type_uuid.to_bytes() == UUID_CCCD.to_bytes() and len(value) >= 2:
            cccd_val = struct.unpack_from("<H", value)[0]
            # Find the value handle (CCCD is always after the value handle)
            value_handle = handle - 1
            if cccd_val & 0x0001:  # notifications enabled
                self.enable_notifications(conn_handle, value_handle)
            else:
                self.disable_notifications(conn_handle, value_handle)
            if cccd_val & 0x0002:  # indications enabled
                self.enable_indications(conn_handle, value_handle)
            else:
                self.disable_indications(conn_handle, value_handle)
        attr.value = value
        handler = self._write_handlers.get(handle)
        if handler is not None:
            result = handler(value)
            if asyncio.iscoroutine(result):
                await result

    async def _handle_prepare_write(self, conn_handle: int, pdu: ATT_Prepare_Write_Request) -> ATTPdu:
        # Prepare Write (0x16): queue a value fragment; nothing is committed
        # until Execute Write. Validate handle/permissions up front and echo
        # the fragment back per spec. The offset rule is enforced on the
        # Execute Write (GAW/BI-09 below).
        attr = self.db.get(pdu.attribute_handle)
        if attr is None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.PREPARE_WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_INVALID_HANDLE,
            )
        sec = self._security(conn_handle)
        perms = int(attr.permissions)
        # GATT/SR/GAW/BI-08: a characteristic gated as write_enc-only carries
        # no plain-write permission bit, and the long-write procedure must
        # reject a prepare on it with Write Not Permitted (0x03) on a plain
        # link. The plain Write Request path keeps the security error
        # 0x05/0x0F (GAP/SEC/SEM/BV-24 expects that to drive pairing) — the
        # asymmetry between the two procedures is what the test suites demand.
        # Encrypted links fall through to the normal gate (0x0C for a short
        # key = GAW/BI-13).
        if (perms & PERM_WRITE_ENC) and not (perms & PERM_WRITE) and not sec.encrypted:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.PREPARE_WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=ATT_ERR_WRITE_NOT_PERMITTED,
            )
        err = self._write_error(attr, sec)
        if err is not None:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.PREPARE_WRITE_REQUEST,
                attribute_handle_in_error=pdu.attribute_handle,
                error_code=err,
            )
        # NOTE: neither the offset rule nor the length rule is enforced here.
        # GATT/SR/GAW/BI-09 has the Lower Tester prepare a fragment with an
        # offset past the value length and expects the echo first, with the
        # Invalid Offset rejection on the Execute Write; BI-33 similarly
        # expects 0x0D on the Execute Write.
        self._prepare_queue.setdefault(conn_handle, []).append(
            (pdu.attribute_handle, pdu.value_offset, pdu.part_attribute_value))
        return ATT_Prepare_Write_Response(
            attribute_handle=pdu.attribute_handle,
            value_offset=pdu.value_offset,
            part_attribute_value=pdu.part_attribute_value,
        )

    async def _handle_execute_write(self, conn_handle: int, pdu: ATT_Execute_Write_Request) -> ATTPdu:
        # Execute Write (0x18): flags 0x00 = cancel all queued prepares,
        # 0x01 = commit them in order.
        queue = self._prepare_queue.pop(conn_handle, [])
        if pdu.flags == 0x01:
            # Assemble per-handle fragments by offset, then commit each. The
            # declared-size rule is enforced here rather than on the individual
            # Prepare Writes: GATT/SR/GAW/BI-33 has the Lower Tester prepare
            # every fragment with valid parameters and expects 0x0D on the
            # Execute Write (Core Vol 3 Part F §3.4.6.4).
            by_handle: dict[int, dict[int, bytes]] = {}
            for handle, offset, frag in queue:
                by_handle.setdefault(handle, {})[offset] = frag
            for handle, frags in by_handle.items():
                attr = self.db.get(handle)
                if attr is None:
                    continue
                # GATT/SR/GAW/BI-09: the invalid-offset rejection is deferred
                # from the Prepare Write (which echoes) to the Execute Write.
                # A fragment landing past the contiguous end of the current
                # value plus the earlier fragments is an Invalid Offset (0x07);
                # valid appends extend the running end exactly (GAW/BV-05) and
                # whole-value rewrites may overlap it (GAW/BV-10 nested writes).
                running_end = len(attr.value)
                for off in sorted(frags):
                    if off > running_end:
                        logger.debug(
                            "ATT execute-write 0x07: handle=0x%04X offset=%d "
                            "beyond value length %d", handle, off, len(attr.value),
                        )
                        return ATT_Error_Response(
                            request_opcode_in_error=ATTOpcode.EXECUTE_WRITE_REQUEST,
                            attribute_handle_in_error=handle,
                            error_code=ATT_ERR_INVALID_OFFSET,
                        )
                    running_end = max(running_end, off + len(frags[off]))
                value = b"".join(frags[off] for off in sorted(frags))
                if self._value_too_long(attr, len(value)):
                    logger.debug(
                        "ATT execute-write 0x0D: handle=0x%04X len=%d max_length=%s",
                        handle, len(value), attr.max_length,
                    )
                    return ATT_Error_Response(
                        request_opcode_in_error=ATTOpcode.EXECUTE_WRITE_REQUEST,
                        attribute_handle_in_error=handle,
                        error_code=ATT_ERR_INVALID_ATTRIBUTE_VALUE_LENGTH,
                    )
                await self._apply_write(conn_handle, handle, value)
        return ATT_Execute_Write_Response()

    def _handle_read_by_group_type(self, conn_handle: int, pdu: ATT_Read_By_Group_Type_Request, bearer_cid: int) -> ATTPdu:
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
        # Attribute data list must fit in (ATT_MTU - 2): 1 byte opcode + 1 byte
        # length are already accounted for by the response header.
        max_data = self._att_mtu(conn_handle, bearer_cid) - 2
        data = b""
        for start, end, value in groups:
            if len(value) + 4 != entry_len:
                break
            if len(data) + entry_len > max_data:
                break
            data += struct.pack("<HH", start, end) + value
        return ATT_Read_By_Group_Type_Response(length=entry_len, attribute_data_list=data)

    def _handle_read_by_type(self, conn_handle: int, pdu: ATT_Read_By_Type_Request, bearer_cid: int) -> ATTPdu:
        # GATT/SR/GAR/BI-08 (Core Vol 3 Part F §3.4.4.1): a handle range that
        # starts past its end (or at 0x0000) is malformed and must be rejected
        # with Invalid Handle at the starting handle — NOT the 0x0A "Attribute
        # Not Found" that a valid-but-empty range gets (GAR/BI-07).
        if pdu.starting_handle == 0x0000 or pdu.starting_handle > pdu.ending_handle:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BY_TYPE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=ATT_ERR_INVALID_HANDLE,
            )
        # 128-bit UUIDs are stored big-endian internally (UUID128) but arrive
        # little-endian on the wire — reverse so find_by_type_in_range matches
        # the stored representation.
        uuid = (UUID16.from_bytes(pdu.attribute_type) if len(pdu.attribute_type) == 2
                else UUID128(bytes(reversed(pdu.attribute_type))))
        attrs = self.db.find_by_type_in_range(pdu.starting_handle, pdu.ending_handle, uuid)
        if not attrs:
            logger.debug(
                "GATT read_by_type uuid=%s range=%04x-%04x -> NOT FOUND",
                pdu.attribute_type.hex(), pdu.starting_handle, pdu.ending_handle,
            )
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.READ_BY_TYPE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,
            )
        logger.debug(
            "GATT read_by_type uuid=%s range=%04x-%04x matched=%d",
            pdu.attribute_type.hex(), pdu.starting_handle, pdu.ending_handle, len(attrs),
        )
        sec = self._security(conn_handle)
        full_value_len = len(attrs[0].value)
        # Truncate to fit ATT_MTU (opcode + length header consume 2 bytes). A
        # value longer than the MTU capacity is truncated, not dropped — the
        # client reads the remainder with Read Blob (GAR/BV-03 "Read using
        # Characteristic UUID" on a long value).
        max_data = self._att_mtu(conn_handle, bearer_cid) - 2
        value_len = min(full_value_len, max_data - 2)
        entry_len = 2 + value_len
        data = b""
        for attr in attrs:
            # "Read Using Characteristic UUID" reuses this opcode with a
            # characteristic-VALUE type: a matching attribute the link may not
            # read yields the security error at its handle (PTS GAR/BI-09..11).
            # Declaration attributes are always readable (plain PERM_READ), so
            # characteristic/service DISCOVERY via this opcode is unaffected.
            err = self._read_error(attr, sec)
            if err is not None:
                if not data:
                    return ATT_Error_Response(
                        request_opcode_in_error=ATTOpcode.READ_BY_TYPE_REQUEST,
                        attribute_handle_in_error=attr.handle,
                        error_code=err,
                    )
                break
            if len(attr.value) != full_value_len:
                break
            if len(data) + entry_len > max_data:
                break
            data += struct.pack("<H", attr.handle) + attr.value[:value_len]
        return ATT_Read_By_Type_Response(length=entry_len, attribute_data_list=data)

    def _handle_find_information(self, conn_handle: int, pdu: ATT_Find_Information_Request, bearer_cid: int) -> ATTPdu:
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
        entry_len = 2 + (2 if fmt == 0x01 else 16)
        # opcode + format header consume 2 bytes.
        max_data = self._att_mtu(conn_handle, bearer_cid) - 2
        data = b""
        for attr in results:
            uuid_bytes = _uuid_le_bytes(attr.type_uuid)
            if len(uuid_bytes) != (2 if fmt == 0x01 else 16):
                break
            if len(data) + entry_len > max_data:
                break
            data += struct.pack("<H", attr.handle) + uuid_bytes
        return ATT_Find_Information_Response(format=fmt, information_data=data)

    def _handle_find_by_type_value(self, pdu: ATT_Find_By_Type_Value_Request) -> ATTPdu:
        """ATT Find By Type Value (0x06) — Discover Primary Service By Service UUID.

        Only defined for the «Primary Service» declaration (type 0x2800); the
        value being matched is the service's UUID. Returns one (found_handle,
        group_end_handle) pair per matching service, else Attribute Not Found.
        PTS GATT/SR/GAD discover-by-UUID cases drive this — without it the IUT
        never answered and PTS ran to the time_guard.
        """
        if pdu.attribute_type != UUID_PRIMARY_SERVICE.value:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.FIND_BY_TYPE_VALUE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,  # Attribute Not Found
            )
        groups = self.db.find_by_group_type(
            pdu.starting_handle, pdu.ending_handle, UUID_PRIMARY_SERVICE)
        info = bytearray()
        for (start_handle, end_handle, svc_value) in groups:
            # Over-air service UUID is LE; the db stores UUID128 big-endian, so
            # accept the reversed form for 16-byte values too.
            if svc_value == pdu.attribute_value or (
                    len(svc_value) == 16
                    and bytes(reversed(svc_value)) == pdu.attribute_value):
                info += struct.pack("<HH", start_handle, end_handle)
        if not info:
            return ATT_Error_Response(
                request_opcode_in_error=ATTOpcode.FIND_BY_TYPE_VALUE_REQUEST,
                attribute_handle_in_error=pdu.starting_handle,
                error_code=0x0A,  # Attribute Not Found
            )
        return ATT_Find_By_Type_Value_Response(handles_info_list=bytes(info))

    # Notification/Indication API

    def enable_notifications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle not in self._notifications_enabled:
            self._notifications_enabled[conn_handle] = set()
        self._notifications_enabled[conn_handle].add(value_handle)

    def disable_notifications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle in self._notifications_enabled:
            self._notifications_enabled[conn_handle].discard(value_handle)

    def enable_indications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle not in self._indications_enabled:
            self._indications_enabled[conn_handle] = set()
        self._indications_enabled[conn_handle].add(value_handle)

    def disable_indications(self, conn_handle: int, value_handle: int) -> None:
        if conn_handle in self._indications_enabled:
            self._indications_enabled[conn_handle].discard(value_handle)

    def on_notification_sent(self, handler: Callable) -> None:
        self._notification_callback = handler

    def on_indication_sent(self, handler: Callable) -> None:
        """Register the bridge used to push an ATT Handle Value Indication
        (0x1D) onto the ATT channel. Separate from notifications (0x1B) so the
        Service Changed characteristic is indicated, not notified."""
        self._indication_callback = handler

    def on_multiple_notification_sent(self, handler: Callable) -> None:
        """Register the bridge used to push an ATT Multiple Handle Value
        Notification (0x23) onto the ATT channel (GATT/SR/GAN/BV-02)."""
        self._multiple_notification_callback = handler

    async def notify_multiple(self, conn_handle: int, handles: list[int]) -> None:
        """Send a Multiple Handle Value Notification (0x23) carrying the values
        of `handles`, but only if the client enabled the Multiple Handle Value
        Notifications CSF bit (GAN/BV-02 step 7: a client without it is ignored).
        """
        state = self._robust.get(conn_handle)
        if state is None or not (state.csf[:1] and state.csf[0] & 0x04):
            logger.debug("GATT notify_multiple conn=0x%04X ignored (mhnv=%s)",
                         conn_handle, bool(state and state.csf[:1] and state.csf[0] & 0x04))
            return
        hlv = []
        for h in handles:
            attr = self.db.get(h)
            if attr is not None:
                hlv.append((h, attr.value))
        logger.debug("GATT notify_multiple conn=0x%04X -> %d tuples", conn_handle, len(hlv))
        if not hlv or self._multiple_notification_callback is None:
            return
        result = self._multiple_notification_callback(hlv, conn_handle)
        if asyncio.iscoroutine(result):
            await result

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

    async def update_attribute_value(self, handle: int, value: bytes) -> None:
        """Store ``value`` in the db and deliver it to the subscribers of
        ``handle`` (notification 0x1B, or indication 0x1D for clients that
        enabled that bit).

        BTP SET_VALUE is the Upper Tester's only lever for making the IUT
        server send a notification/indication — auto-pts has no dedicated
        "send notification" opcode. Its ``hdl_wid_92``/``hdl_wid_98`` have the
        Lower Tester subscribe, then set the value and wait on the air for the
        ATT PDU; without the push the MMI stalls until the time guard
        (GATT/SR/GAN/BV-01)."""
        attr = self.db.get(handle)
        if attr is None:
            return
        attr.value = value
        if self._notification_callback:
            for conn, enabled in list(self._notifications_enabled.items()):
                if handle in enabled:
                    await self.notify(handle, value, [conn])
        if self._indication_callback:
            for conn, enabled in list(self._indications_enabled.items()):
                if handle in enabled:
                    await self.indicate(handle, value, conn)

    async def indicate(self, handle: int, value: bytes, connection: int) -> bool:
        """Send an indication (requires confirmation from client). Returns True
        if the indication bridge delivered it (the ATT channel was present),
        False if the connection is gone."""
        if self._indication_callback:
            result = self._indication_callback(handle, value, connection)
            if asyncio.iscoroutine(result):
                result = await result
            return bool(result)
        return False

    async def indicate_service_changed(self, start_handle: int, end_handle: int) -> None:
        """Send a Service Changed indication (GATT/SR/GAS/BV-01) to every
        connection that has enabled indication on the Service Changed CCCD.

        The characteristic value is the affected handle range (start + end).
        Called when the server db changes (BTP CHANGE_DATABASE). A client that is
        disconnected when the change happens can't take the indication, so it is
        remembered and resent on that client's first request after reconnect."""
        sc_handle = self.find_characteristic_value_handle(UUID_SERVICE_CHANGED)
        if sc_handle is None:
            logger.warning("GATT indicate_service_changed: no SC characteristic in db")
            return
        value = struct.pack("<HH", start_handle, end_handle)
        for conn, enabled in list(self._indications_enabled.items()):
            if sc_handle in enabled:
                if await self.indicate(sc_handle, value, conn):
                    self._service_changed_pending.pop(conn, None)
                    logger.debug("GATT indicate_service_changed conn=0x%04X sent", conn)
                else:
                    self._service_changed_pending[conn] = (start_handle, end_handle)
                    logger.debug("GATT indicate_service_changed conn=0x%04X deferred", conn)
            else:
                logger.debug(
                    "GATT indicate_service_changed conn=0x%04X not SC-subscribed (enabled=%s)",
                    conn, [hex(h) for h in enabled],
                )

    async def on_connection_opened(self, conn_handle: int) -> None:
        """Deliver a Service Changed indication deferred while `conn_handle` was
        disconnected (GAS/BV-01, BV-07). Wired to the stack's connection-open
        path: the Lower Tester reconnects and waits for the indication without
        sending any ATT request first, so the flush must be driven by the
        connection itself, not by the client's next PDU."""
        pending = self._service_changed_pending.pop(conn_handle, None)
        if pending is None:
            return
        logger.debug("GATT on_connection_opened conn=0x%04X flushing pending SC", conn_handle)
        sc_handle = self.find_characteristic_value_handle(UUID_SERVICE_CHANGED)
        if sc_handle is None:
            return
        start_handle, end_handle = pending
        value = struct.pack("<HH", start_handle, end_handle)
        await self.indicate(sc_handle, value, conn_handle)
        # Receiving the Service Changed indication makes the client change-aware
        # (Core Vol 3 Part G §2.5.2.1). Clear change-unaware so the client's next
        # read — which may arrive before it confirms the indication — returns the
        # value rather than Database Out Of Sync (GAS/BV-07 step 6).
        state = self._robust.get(conn_handle)
        if state is not None:
            state.change_unaware = False
            state.synced_pending.clear()

    def find_characteristic_value_handle(self, uuid: UUID16 | UUID128) -> int | None:
        uuid_bytes = uuid.to_bytes()
        for attr in self.db._attrs:
            if attr.type_uuid.to_bytes() == uuid_bytes and attr.type_uuid.to_bytes() != UUID_CHARACTERISTIC.to_bytes():
                return attr.handle
        return None


class GATTClient:
    """GATT Client — wraps ATTBearer for service discovery and attribute access."""

    def __init__(
        self,
        bearer: ATTBearer,
        *,
        connection_handle: int | None = None,
        on_insufficient_encryption=None,
    ) -> None:
        self._bearer = bearer
        self._connection_handle = connection_handle
        self._on_insufficient_encryption = on_insufficient_encryption

    @property
    def connection_handle(self) -> int | None:
        """The ACL connection handle this client is bound to (None if unbound)."""
        return self._connection_handle

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

    async def discover_included_services(
        self, start_handle: int, end_handle: int
    ) -> list[tuple[int, int, int, bytes]]:
        """Discover Include declarations (0x2802) in a handle range.

        Returns ``[(include_handle, inc_start_handle, inc_end_handle, uuid_bytes),
        ...]`` — the included service's own group range and UUID, read from the
        Include declaration value. Drives BTP GATT FIND_INCLUDED_SVCS (0x0d).
        """
        includes: list[tuple[int, int, int, bytes]] = []
        start = start_handle
        while start <= end_handle:
            req = ATT_Read_By_Type_Request(
                starting_handle=start,
                ending_handle=end_handle,
                attribute_type=UUID_INCLUDE.to_bytes(),
            )
            resp = await self._bearer._request(req, ATTOpcode.READ_BY_TYPE_RESPONSE)
            if isinstance(resp, ATT_Error_Response):
                break
            if not isinstance(resp, ATT_Read_By_Type_Response):
                break
            entry_len = resp.length
            data = resp.attribute_data_list
            offset = 0
            last_handle = 0
            # Include declaration value = inc_start(2)+inc_end(2)+uuid(2|16), so the
            # full entry (handle(2)+value) is at least 8 bytes.
            while entry_len >= 8 and offset + entry_len <= len(data):
                incl_handle, inc_start, inc_end = struct.unpack_from("<HHH", data, offset)
                uuid = data[offset + 6: offset + entry_len]
                if incl_handle >= start:
                    includes.append((incl_handle, inc_start, inc_end, uuid))
                    last_handle = incl_handle
                offset += entry_len
            if last_handle == 0 or last_handle < start:
                break
            start = last_handle + 1
        return includes

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

    async def _request_with_retry(self, coro_factory):
        """Run coro_factory(); on ATTError 0x0F call on_insufficient_encryption and retry once."""
        try:
            return await coro_factory()
        except ATTError as exc:
            if exc.error_code != 0x0F or self._on_insufficient_encryption is None:
                raise
            await self._on_insufficient_encryption(self._connection_handle)
            return await coro_factory()

    async def exchange_mtu(self, mtu: int) -> int:
        """ATT MTU Exchange (Core Spec Vol 3 Part F §3.4.2) — returns negotiated MTU."""
        return await self._bearer.exchange_mtu(mtu)

    def on_notification(self, cb) -> None:
        """Register a callback fired on each incoming Handle Value Notification.

        Signature: cb(value_handle: int, value: bytes) -> None | Awaitable[None]
        Replaces any previously-registered handler on the underlying ATT bearer.
        """
        self._bearer.set_notification_handler(cb)

    def on_indication(self, cb) -> None:
        """Register a callback fired on each incoming Handle Value Indication.

        Signature: cb(value_handle: int, value: bytes) -> None | Awaitable[None]
        The bearer auto-sends the Handle Value Confirmation after the callback.
        """
        self._bearer.set_indication_handler(cb)

    async def read_characteristic(self, handle: int) -> bytes:
        return await self._request_with_retry(lambda: self._bearer.read(handle))

    async def read_long_characteristic(self, handle: int, offset: int = 0) -> bytes:
        """Read Long Characteristic Value (ATT Read Blob, Vol 3 Part F §3.4.4.5).

        Reads the full (possibly > ATT_MTU-1) attribute value: an initial Read
        (offset 0) followed by Read Blob Requests until a short chunk returns.
        With ``offset`` > 0, starts directly with Read Blob at that offset.
        """
        if offset == 0:
            return await self._request_with_retry(lambda: self._bearer.read_long(handle))
        return await self._request_with_retry(lambda: self._bearer.read_blob(handle, offset))

    async def read_multiple_characteristic(self, handles: list[int]) -> bytes:
        """Read Multiple Characteristic Values (ATT Read Multiple, Vol 3 Part F §3.4.4.3).

        Sends a single ATT Read Multiple Request for ``handles`` — the PTS lower
        tester checks for that specific PDU (individual Reads don't satisfy it).
        """
        return await self._request_with_retry(lambda: self._bearer.read_multiple(handles))

    async def read_multiple_variable_characteristic(
        self, handles: list[int], *, bearer=None,
    ) -> list[bytes]:
        """Read Multiple Variable Length Characteristic Values (Vol 3 Part F §3.4.4.4).

        Sends a single ATT Read Multiple Variable Length Request; returns the
        per-handle list of values. ``bearer`` overrides the default ATT bearer —
        GATT.TS §4.6.1 (GAR/BV-10) multiplexes these requests across bearers,
        and the bearer choice is IUT policy (BTP 0x20 has no bearer field).
        """
        target = bearer if bearer is not None else self._bearer
        return await self._request_with_retry(lambda: target.read_multiple_variable(handles))

    async def read_using_characteristic_uuid(
        self, start_handle: int, end_handle: int, uuid: bytes
    ) -> tuple[int, list[tuple[int, bytes]]]:
        """Read Using Characteristic UUID (ATT Read By Type, Vol 3 Part F §3.4.4.1).

        Sends ATT Read By Type Request with ``uuid`` (2- or 16-byte little-endian
        attribute type) over ``[start_handle, end_handle]`` and paginates until the
        range is covered. Returns ``(att_status, [(value_handle, value), ...])`` —
        ``att_status`` is 0x00 when at least one value was read, otherwise the ATT
        error code from the server (e.g. 0x0A Attribute Not Found).
        """
        results: list[tuple[int, bytes]] = []
        start = start_handle
        while start <= end_handle:
            req = ATT_Read_By_Type_Request(
                starting_handle=start,
                ending_handle=end_handle,
                attribute_type=uuid,
            )
            resp = await self._bearer._request(req, ATTOpcode.READ_BY_TYPE_RESPONSE)
            if isinstance(resp, ATT_Error_Response):
                # "Attribute Not Found" after partial results just ends pagination.
                return (0x00 if results else resp.error_code), results
            if not isinstance(resp, ATT_Read_By_Type_Response):
                break
            entry_len = resp.length
            data = resp.attribute_data_list
            offset = 0
            last_handle = 0
            while entry_len >= 3 and offset + entry_len <= len(data):
                handle = struct.unpack_from("<H", data, offset)[0]
                value = data[offset + 2: offset + entry_len]
                results.append((handle, value))
                last_handle = handle
                offset += entry_len
            if last_handle == 0 or last_handle >= end_handle:
                break
            start = last_handle + 1
        return 0x00, results

    async def write_characteristic(self, handle: int, value: bytes) -> None:
        await self._request_with_retry(lambda: self._bearer.write(handle, value))

    async def write_long_characteristic(self, handle: int, value: bytes, offset: int = 0) -> None:
        """Write Long Characteristic Value (ATT Prepare/Execute Write, Vol 3 Part F §3.4.6).

        Chunks ``value`` into Prepare Write Requests at the negotiated MTU and
        commits with Execute Write. Distinct from :meth:`write_characteristic`
        (a single ATT Write Request) — required when the value exceeds the
        ATT_MTU-3 single-write payload or the peer tests the long-write procedure.
        ``offset`` is the starting value offset for the prepare writes.
        """
        await self._request_with_retry(lambda: self._bearer.write_long(handle, value, offset=offset))
