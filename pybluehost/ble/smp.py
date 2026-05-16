"""SMP (Security Manager Protocol) — pairing, crypto, and bond management."""
from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Awaitable, Callable, Protocol, runtime_checkable

import asyncio

from pybluehost.core.address import BDAddress
from pybluehost.core.statemachine import StateMachine
from pybluehost.core.types import IOCapability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pairing lifecycle logging helpers
# ---------------------------------------------------------------------------

_PAIRING_FAILURE_NAMES: dict[int, str] = {
    0x01: "Passkey_Entry_Failed",
    0x02: "Out_Of_Band",
    0x03: "Authentication_Requirements",
    0x04: "Confirm_Value_Failed",
    0x05: "Pairing_Not_Supported",
    0x06: "Encryption_Key_Size",
    0x07: "Command_Not_Supported",
    0x08: "Unspecified_Reason",
    0x09: "Repeated_Attempts",
}


def _log_pairing_started(*, handle: int, io_caps: str, bonding: bool, mitm: bool) -> None:
    logger.info(
        "SMP pairing started handle=0x%04X io_caps=%s bonding=%s mitm=%s",
        handle, io_caps, "YES" if bonding else "NO", "YES" if mitm else "NO",
    )


def _log_pairing_phase(*, handle: int, phase: str) -> None:
    logger.info("SMP -> %s on handle=0x%04X", phase, handle)


def _log_pairing_complete(*, handle: int, peer_addr: str, ltk_stored: bool) -> None:
    logger.info(
        "SMP paired with %s (handle=0x%04X) ltk_stored=%s",
        peer_addr, handle, "YES" if ltk_stored else "NO",
    )


def _log_pairing_failed(*, handle: int, reason: int) -> None:
    name = _PAIRING_FAILURE_NAMES.get(reason, f"0x{reason:02X}")
    logger.warning("SMP pairing failed handle=0x%04X reason=%s", handle, name)


# ---------------------------------------------------------------------------
# SMP Code (opcode) enum
# ---------------------------------------------------------------------------

class SMPCode(IntEnum):
    PAIRING_REQUEST = 0x01
    PAIRING_RESPONSE = 0x02
    PAIRING_CONFIRM = 0x03
    PAIRING_RANDOM = 0x04
    PAIRING_FAILED = 0x05
    ENCRYPTION_INFORMATION = 0x06
    MASTER_IDENTIFICATION = 0x07
    IDENTITY_INFORMATION = 0x08
    IDENTITY_ADDRESS_INFORMATION = 0x09
    SIGNING_INFORMATION = 0x0A
    SECURITY_REQUEST = 0x0B
    PAIRING_PUBLIC_KEY = 0x0C
    PAIRING_DHKEY_CHECK = 0x0D
    KEYPRESS_NOTIFICATION = 0x0E


# Pairing Failed reasons (Core 5.4 Vol 3 Part H 3.5.5)
PAIRING_FAILED_REASON_PASSKEY_ENTRY_FAILED = 0x01
PAIRING_FAILED_REASON_OOB_NOT_AVAILABLE     = 0x02
PAIRING_FAILED_REASON_AUTH_REQUIREMENTS     = 0x03
PAIRING_FAILED_REASON_CONFIRM_VALUE_FAILED  = 0x04
PAIRING_FAILED_REASON_PAIRING_NOT_SUPPORTED = 0x05
PAIRING_FAILED_REASON_UNSPECIFIED           = 0x08


# ---------------------------------------------------------------------------
# SMP PDU base and concrete classes
# ---------------------------------------------------------------------------

@dataclass
class SMPPdu:
    """Base class for SMP PDUs."""

    def to_bytes(self) -> bytes:
        raise NotImplementedError


@dataclass
class SMPPairingRequest(SMPPdu):
    io_capability: int = 0x03
    oob_data_flag: int = 0x00
    auth_req: int = 0x01
    max_key_size: int = 16
    init_key_dist: int = 0x00
    resp_key_dist: int = 0x00

    def to_bytes(self) -> bytes:
        return bytes([
            SMPCode.PAIRING_REQUEST,
            self.io_capability, self.oob_data_flag, self.auth_req,
            self.max_key_size, self.init_key_dist, self.resp_key_dist,
        ])

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingRequest:
        return cls(
            io_capability=data[0], oob_data_flag=data[1], auth_req=data[2],
            max_key_size=data[3], init_key_dist=data[4], resp_key_dist=data[5],
        )


@dataclass
class SMPPairingResponse(SMPPdu):
    io_capability: int = 0x03
    oob_data_flag: int = 0x00
    auth_req: int = 0x01
    max_key_size: int = 16
    init_key_dist: int = 0x00
    resp_key_dist: int = 0x00

    def to_bytes(self) -> bytes:
        return bytes([
            SMPCode.PAIRING_RESPONSE,
            self.io_capability, self.oob_data_flag, self.auth_req,
            self.max_key_size, self.init_key_dist, self.resp_key_dist,
        ])

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingResponse:
        return cls(
            io_capability=data[0], oob_data_flag=data[1], auth_req=data[2],
            max_key_size=data[3], init_key_dist=data[4], resp_key_dist=data[5],
        )


@dataclass
class SMPPairingConfirm(SMPPdu):
    confirm_value: bytes = field(default_factory=lambda: bytes(16))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.PAIRING_CONFIRM]) + self.confirm_value

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingConfirm:
        return cls(confirm_value=data[:16])


@dataclass
class SMPPairingRandom(SMPPdu):
    random_value: bytes = field(default_factory=lambda: bytes(16))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.PAIRING_RANDOM]) + self.random_value

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingRandom:
        return cls(random_value=data[:16])


@dataclass
class SMPPairingFailed(SMPPdu):
    reason: int = 0x00

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.PAIRING_FAILED, self.reason])

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingFailed:
        return cls(reason=data[0])


@dataclass
class SMPEncryptionInformation(SMPPdu):
    long_term_key: bytes = field(default_factory=lambda: bytes(16))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.ENCRYPTION_INFORMATION]) + self.long_term_key

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPEncryptionInformation:
        return cls(long_term_key=data[:16])


@dataclass
class SMPMasterIdentification(SMPPdu):
    ediv: int = 0
    rand: bytes = field(default_factory=lambda: bytes(8))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.MASTER_IDENTIFICATION]) + struct.pack("<H", self.ediv) + self.rand

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPMasterIdentification:
        ediv = struct.unpack_from("<H", data, 0)[0]
        rand = data[2:10]
        return cls(ediv=ediv, rand=rand)


@dataclass
class SMPIdentityInformation(SMPPdu):
    irk: bytes = field(default_factory=lambda: bytes(16))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.IDENTITY_INFORMATION]) + self.irk

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPIdentityInformation:
        return cls(irk=data[:16])


@dataclass
class SMPIdentityAddressInformation(SMPPdu):
    addr_type: int = 0x00
    bd_addr: bytes = field(default_factory=lambda: bytes(6))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.IDENTITY_ADDRESS_INFORMATION, self.addr_type]) + self.bd_addr

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPIdentityAddressInformation:
        return cls(addr_type=data[0], bd_addr=data[1:7])


@dataclass
class SMPSigningInformation(SMPPdu):
    signature_key: bytes = field(default_factory=lambda: bytes(16))

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.SIGNING_INFORMATION]) + self.signature_key

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPSigningInformation:
        return cls(signature_key=data[:16])


@dataclass
class SMPSecurityRequest(SMPPdu):
    auth_req: int = 0x01

    def to_bytes(self) -> bytes:
        return bytes([SMPCode.SECURITY_REQUEST, self.auth_req])

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPSecurityRequest:
        return cls(auth_req=data[0])


_PDU_MAP: dict[int, type[SMPPdu]] = {
    SMPCode.PAIRING_REQUEST: SMPPairingRequest,
    SMPCode.PAIRING_RESPONSE: SMPPairingResponse,
    SMPCode.PAIRING_CONFIRM: SMPPairingConfirm,
    SMPCode.PAIRING_RANDOM: SMPPairingRandom,
    SMPCode.PAIRING_FAILED: SMPPairingFailed,
    SMPCode.ENCRYPTION_INFORMATION: SMPEncryptionInformation,
    SMPCode.MASTER_IDENTIFICATION: SMPMasterIdentification,
    SMPCode.IDENTITY_INFORMATION: SMPIdentityInformation,
    SMPCode.IDENTITY_ADDRESS_INFORMATION: SMPIdentityAddressInformation,
    SMPCode.SIGNING_INFORMATION: SMPSigningInformation,
    SMPCode.SECURITY_REQUEST: SMPSecurityRequest,
}


def decode_smp_pdu(data: bytes) -> SMPPdu:
    """Decode raw SMP PDU bytes into the appropriate PDU object."""
    code = data[0]
    pdu_cls = _PDU_MAP.get(code)
    if pdu_cls is None:
        raise ValueError(f"Unknown SMP code: 0x{code:02X}")
    return pdu_cls.from_bytes(data[1:])


# ---------------------------------------------------------------------------
# SMP Crypto functions (BT Core Spec v5.4 Vol 3 Part H)
# ---------------------------------------------------------------------------

def _aes_ecb(key: bytes, plaintext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()


def _aes_cmac(key: bytes, message: bytes) -> bytes:
    from cryptography.hazmat.primitives.cmac import CMAC
    from cryptography.hazmat.primitives.ciphers import algorithms

    c = CMAC(algorithms.AES(key))
    c.update(message)
    return c.finalize()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


class SMPCrypto:
    """BT Spec SMP cryptographic toolbox (all static methods)."""

    @staticmethod
    def c1(
        k: bytes, r: bytes,
        preq: bytes, pres: bytes,
        iat: int, rat: int,
        ia: bytes, ra: bytes,
    ) -> bytes:
        """Legacy pairing confirm value (BT Spec Vol 3 Part H §2.2.3)."""
        # p1 = pres || preq || rat || iat (LSB first per spec encoding)
        p1 = bytearray(16)
        p1[0] = iat
        p1[1] = rat
        p1[2:9] = preq
        p1[9:16] = pres

        # p2 = padding(4) || ia(6) || ra(6)
        p2 = bytearray(16)
        p2[0:6] = ra
        p2[6:12] = ia
        # p2[12:16] = 0x00 padding

        # confirm = e(k, e(k, r XOR p1) XOR p2)
        step1 = _aes_ecb(k, _xor(r, bytes(p1)))
        return _aes_ecb(k, _xor(step1, bytes(p2)))

    @staticmethod
    def s1(k: bytes, r1: bytes, r2: bytes) -> bytes:
        """Legacy STK generation (BT Spec Vol 3 Part H §2.2.4).

        r' = r1[8:16] || r2[8:16] (least significant 8 bytes of each), result = e(k, r').
        """
        r_prime = r1[8:16] + r2[8:16]
        return _aes_ecb(k, r_prime)

    @staticmethod
    def f4(U: bytes, V: bytes, X: bytes, Z: int) -> bytes:
        """SC confirm value (BT Spec Vol 3 Part H §2.2.6).

        f4(U, V, X, Z) = AES-CMAC_X(U || V || Z)
        """
        message = U + V + bytes([Z])
        return _aes_cmac(X, message)

    @staticmethod
    def f5(
        W: bytes, N1: bytes, N2: bytes, A1: bytes, A2: bytes,
    ) -> tuple[bytes, bytes]:
        """SC key generation (BT Spec Vol 3 Part H §2.2.7).

        Returns (MacKey, LTK).
        """
        SALT = bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")
        T = _aes_cmac(SALT, W)
        # keyID = "btle" in ASCII
        key_id = b"btle"
        # Length = 256 encoded as 2 bytes big-endian
        length = b"\x01\x00"

        # MacKey = AES-CMAC_T(Counter=0 || keyID || N1 || N2 || A1 || A2 || Length)
        m0 = bytes([0x00]) + key_id + N1 + N2 + A1 + A2 + length
        mac_key = _aes_cmac(T, m0)

        # LTK = AES-CMAC_T(Counter=1 || keyID || N1 || N2 || A1 || A2 || Length)
        m1 = bytes([0x01]) + key_id + N1 + N2 + A1 + A2 + length
        ltk = _aes_cmac(T, m1)

        return mac_key, ltk

    @staticmethod
    def f6(
        W: bytes, N1: bytes, N2: bytes,
        R: bytes, IOcap: bytes, A1: bytes, A2: bytes,
    ) -> bytes:
        """SC DHKey check (BT Spec Vol 3 Part H §2.2.8).

        f6(W, N1, N2, R, IOcap, A1, A2) = AES-CMAC_W(N1 || N2 || R || IOcap || A1 || A2)
        """
        message = N1 + N2 + R + IOcap + A1 + A2
        return _aes_cmac(W, message)

    @staticmethod
    def g2(U: bytes, V: bytes, X: bytes, Y: bytes) -> int:
        """SC numeric comparison (BT Spec Vol 3 Part H §2.2.9).

        g2(U, V, X, Y) = AES-CMAC_X(U || V || Y) mod 2^32, returned as uint32.
        """
        message = U + V + Y
        mac = _aes_cmac(X, message)
        # Last 4 bytes as big-endian uint32
        return struct.unpack(">I", mac[12:16])[0]

    @staticmethod
    def ah(k: bytes, r: bytes) -> bytes:
        """RPA hash function (BT Spec Vol 3 Part H §2.2.2).

        ah(k, r) = e(k, r') mod 2^24, where r' is r zero-padded to 16 bytes (MSB).
        """
        # r is 3 bytes; pad on left to make 16 bytes
        padded = bytes(13) + r
        encrypted = _aes_ecb(k, padded)
        # Return last 3 bytes
        return encrypted[13:16]

    @staticmethod
    def h6(W: bytes, key_id: bytes) -> bytes:
        """Link key conversion function (BT Spec Vol 3 Part H §2.2.10).

        h6(W, keyID) = AES-CMAC_W(keyID)
        """
        return _aes_cmac(W, key_id)

    @staticmethod
    def h7(SALT: bytes, W: bytes) -> bytes:
        """Link key conversion function (BT Spec Vol 3 Part H §2.2.11).

        h7(SALT, W) = AES-CMAC_SALT(W)
        """
        return _aes_cmac(SALT, W)


# ---------------------------------------------------------------------------
# BondInfo
# ---------------------------------------------------------------------------

@dataclass
class BondInfo:
    """Bond information for a single peer."""
    peer_address: BDAddress
    address_type: int = 0
    ltk: bytes | None = None
    irk: bytes | None = None
    csrk: bytes | None = None
    ediv: int = 0
    rand: bytes = field(default_factory=lambda: b"\x00" * 8)
    key_size: int = 16
    authenticated: bool = False
    sc: bool = False
    link_key: bytes | None = None
    link_key_type: int | None = None
    ctkd_derived: bool = False


# ---------------------------------------------------------------------------
# BondStorage Protocol + JsonBondStorage
# ---------------------------------------------------------------------------

@runtime_checkable
class BondStorage(Protocol):
    """Interface for persistent bond storage."""

    async def save_bond(self, bond: BondInfo) -> None: ...
    async def load_bond(self, address: BDAddress) -> BondInfo | None: ...
    async def delete_bond(self, address: BDAddress) -> None: ...
    async def list_bonds(self) -> list[BondInfo]: ...


def _decode_legacy_rand(value: int | str | None) -> bytes:
    """Decode the bond ``rand`` field, accepting both legacy int and new hex string.

    Pre-Sub-Plan-1 stored rand as an int; current code stores it as an 8-byte
    hex string. Old JSON files must still load.
    """
    if isinstance(value, int):
        return value.to_bytes(8, "little")
    if isinstance(value, str):
        return bytes.fromhex(value)
    return b"\x00" * 8


class JsonBondStorage:
    """JSON file-based bond storage."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        if self._path.exists():
            with open(self._path) as f:
                self._data = json.load(f)

    async def save_bond(self, bond: BondInfo) -> None:
        key = str(bond.peer_address)
        self._data[key] = {
            "peer_address": str(bond.peer_address),
            "address_type": bond.address_type,
            "ltk": bond.ltk.hex() if bond.ltk else None,
            "irk": bond.irk.hex() if bond.irk else None,
            "csrk": bond.csrk.hex() if bond.csrk else None,
            "ediv": bond.ediv,
            "rand": bond.rand.hex(),
            "key_size": bond.key_size,
            "authenticated": bond.authenticated,
            "sc": bond.sc,
            "link_key": bond.link_key.hex() if bond.link_key else None,
            "link_key_type": bond.link_key_type,
            "ctkd_derived": bond.ctkd_derived,
        }
        self._flush()

    async def load_bond(self, address: BDAddress) -> BondInfo | None:
        entry = self._data.get(str(address))
        if entry is None:
            return None
        return BondInfo(
            peer_address=BDAddress.from_string(entry["peer_address"]),
            address_type=entry.get("address_type", 0),
            ltk=bytes.fromhex(entry["ltk"]) if entry.get("ltk") else None,
            irk=bytes.fromhex(entry["irk"]) if entry.get("irk") else None,
            csrk=bytes.fromhex(entry["csrk"]) if entry.get("csrk") else None,
            ediv=entry.get("ediv", 0),
            rand=_decode_legacy_rand(entry.get("rand", "0000000000000000")),
            key_size=entry.get("key_size", 16),
            authenticated=entry.get("authenticated", False),
            sc=entry.get("sc", False),
            link_key=bytes.fromhex(entry["link_key"]) if entry.get("link_key") else None,
            link_key_type=entry.get("link_key_type"),
            ctkd_derived=entry.get("ctkd_derived", False),
        )

    async def delete_bond(self, address: BDAddress) -> None:
        self._data.pop(str(address), None)
        self._flush()

    async def list_bonds(self) -> list[BondInfo]:
        result = []
        for entry in self._data.values():
            result.append(BondInfo(
                peer_address=BDAddress.from_string(entry["peer_address"]),
                address_type=entry.get("address_type", 0),
                ltk=bytes.fromhex(entry["ltk"]) if entry.get("ltk") else None,
                irk=bytes.fromhex(entry["irk"]) if entry.get("irk") else None,
                csrk=bytes.fromhex(entry["csrk"]) if entry.get("csrk") else None,
                ediv=entry.get("ediv", 0),
                rand=_decode_legacy_rand(entry.get("rand", "0000000000000000")),
                key_size=entry.get("key_size", 16),
                authenticated=entry.get("authenticated", False),
                sc=entry.get("sc", False),
                link_key=bytes.fromhex(entry["link_key"]) if entry.get("link_key") else None,
                link_key_type=entry.get("link_key_type"),
                ctkd_derived=entry.get("ctkd_derived", False),
            ))
        return result

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)


# ---------------------------------------------------------------------------
# PairingDelegate Protocol + AutoAcceptDelegate
# ---------------------------------------------------------------------------

class PairingDelegate(Protocol):
    """User interaction interface for SMP pairing decisions."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool: ...
    async def confirm_passkey(self, passkey: int) -> bool: ...
    async def confirm_numeric_comparison(self, value: int) -> bool: ...
    async def get_passkey(self) -> int: ...
    async def display_passkey(self, passkey: int) -> None: ...


class AutoAcceptDelegate:
    """Default delegate that auto-accepts everything (for testing)."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, passkey: int) -> bool:
        return True

    async def confirm_numeric_comparison(self, value: int) -> bool:
        return True

    async def get_passkey(self) -> int:
        return 0

    async def display_passkey(self, passkey: int) -> None:
        pass


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------

class SMPState(IntEnum):
    IDLE = 0
    FEATURE_EXCHANGE = 1
    CONFIRMING = 2
    RANDOM_EXCHANGE = 3
    STK_ENCRYPTING = 4
    KEY_DISTRIBUTION = 5
    BONDED = 6
    FAILED = 7


class SMPEvent(IntEnum):
    LOCAL_PAIR_REQUEST = 0
    PAIRING_REQ_RX = 1
    PAIRING_RSP_RX = 2
    PAIRING_CONFIRM_RX = 3
    PAIRING_RANDOM_RX = 4
    ENCRYPTION_CHANGE_SUCCESS = 5
    ENCRYPTION_CHANGE_FAILED = 6
    ENCRYPTION_INFO_RX = 7
    MASTER_IDENT_RX = 8
    IDENTITY_INFO_RX = 9
    IDENTITY_ADDR_RX = 10
    SIGNING_INFO_RX = 11
    KEYS_RECEIVED = 12
    PAIRING_FAILED_RX = 13
    TIMEOUT = 14
    DISCONNECTED = 15


class PairingRole(IntEnum):
    INITIATOR = 0
    RESPONDER = 1


# ---------------------------------------------------------------------------
# Per-connection pairing context
# ---------------------------------------------------------------------------

@dataclass
class SMPPairingContext:
    """Per-connection pairing state container."""

    connection_handle: int
    peer_address: BDAddress
    role: PairingRole
    state_machine: StateMachine

    # Feature exchange
    local_io_caps: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    peer_io_caps: IOCapability | None = None
    local_auth_req: int = 0
    peer_auth_req: int = 0
    local_max_key_size: int = 16
    peer_max_key_size: int = 16
    local_init_key_dist: int = 0
    peer_init_key_dist: int = 0
    local_resp_key_dist: int = 0
    peer_resp_key_dist: int = 0
    saved_pairing_request: bytes = b""
    saved_pairing_response: bytes = b""

    # Phase 2 working state
    tk: bytes = field(default_factory=lambda: b"\x00" * 16)
    local_random: bytes = b""
    peer_random: bytes = b""
    local_confirm: bytes = b""
    peer_confirm: bytes = b""
    stk: bytes = b""

    # Phase 3 collected (from peer)
    received_ltk: bytes = b""
    received_ediv: int = 0
    received_rand: bytes = b""
    received_irk: bytes = b""
    received_identity_address: tuple[int, bytes] = field(default_factory=lambda: (0, b""))
    received_csrk: bytes = b""

    # Phase 3 generated locally (sent to peer; Peripheral needs these for reconnect LTK replies)
    local_ltk: bytes = b""
    local_ediv: int = 0
    local_rand: bytes = b""

    # Bookkeeping
    bondable: bool = True
    local_address: BDAddress | None = None
    pairing_complete: "asyncio.Future[None] | None" = None
    send: "Callable[[bytes], Awaitable[None]] | None" = None
    _hci: object | None = None
    _bond_storage: "BondStorage | None" = None

    @classmethod
    def create(
        cls,
        *,
        connection_handle: int,
        peer_address: BDAddress,
        role: PairingRole,
        send: "Callable[[bytes], Awaitable[None]] | None" = None,
    ) -> "SMPPairingContext":
        sm: StateMachine[SMPState, SMPEvent] = StateMachine(
            name=f"SMP[h=0x{connection_handle:04X}]",
            initial=SMPState.IDLE,
        )
        return cls(
            connection_handle=connection_handle,
            peer_address=peer_address,
            role=role,
            state_machine=sm,
            send=send,
        )


# ---------------------------------------------------------------------------
# SMPManager (minimal state machine holder)
# ---------------------------------------------------------------------------

class SMPManager:
    """SMP pairing state machine manager."""

    def __init__(
        self,
        hci: object | None = None,
        bond_storage: BondStorage | None = None,
        delegate: PairingDelegate | AutoAcceptDelegate | None = None,
        local_io_caps: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT,
        bondable: bool = True,
        local_address: BDAddress | None = None,
    ) -> None:
        self._hci = hci
        self._bond_storage = bond_storage
        self._delegate = delegate or AutoAcceptDelegate()
        self._local_io_caps = local_io_caps
        self._bondable = bondable
        self._local_address = local_address
        self._senders: dict[int, Callable[[bytes], Awaitable[None]]] = {}
        self._peer_addrs: dict[int, BDAddress] = {}
        self._contexts: dict[int, SMPPairingContext] = {}

    def bind_channel(
        self,
        connection_handle: int,
        send: Callable[[bytes], Awaitable[None]],
        peer_address: BDAddress | None = None,
    ) -> None:
        """Bind an L2CAP CID_SMP send-callable to a connection handle."""
        self._senders[connection_handle] = send
        if peer_address is not None:
            self._peer_addrs[connection_handle] = peer_address

    def register_peer_address(self, connection_handle: int, address: BDAddress) -> None:
        """Bind a peer BD address to an LE connection handle.

        Called from Stack on LE_Connection_Complete so SMP can:
        - Look up the bond by peer address on reconnect
        - Build the c1/s1 parameters for legacy pairing using the actual peer addr
        - Persist BondInfo.peer_address correctly after Phase 3
        """
        self._peer_addrs[connection_handle] = address

    def unbind_channel(self, connection_handle: int) -> None:
        """Remove the L2CAP send-callable and tear down any active context."""
        self._senders.pop(connection_handle, None)
        self._peer_addrs.pop(connection_handle, None)
        ctx = self._contexts.pop(connection_handle, None)
        if ctx is not None and ctx.state_machine.state not in (SMPState.BONDED, SMPState.FAILED):
            asyncio.create_task(ctx.state_machine.fire(SMPEvent.DISCONNECTED))

    def set_delegate(
        self,
        delegate: PairingDelegate | AutoAcceptDelegate,
    ) -> None:
        self._delegate = delegate

    def set_hci(self, hci: object) -> None:
        self._hci = hci

    def set_local_address(self, address: BDAddress) -> None:
        self._local_address = address

    def get_context(self, connection_handle: int) -> SMPPairingContext | None:
        return self._contexts.get(connection_handle)

    async def start_initiator(self, connection_handle: int) -> "asyncio.Future[None]":
        """Begin Initiator-role pairing on a connected LE link."""
        from pybluehost.ble._smp_state import register_transitions
        if connection_handle in self._contexts:
            raise RuntimeError(f"SMP context already active for handle=0x{connection_handle:04X}")
        send = self._senders.get(connection_handle)
        if send is None:
            raise RuntimeError(f"No SMP channel bound for handle=0x{connection_handle:04X}")
        peer = self._peer_addrs.get(connection_handle)
        if peer is None:
            raise RuntimeError(f"Peer address unknown for handle=0x{connection_handle:04X}")
        ctx = SMPPairingContext.create(
            connection_handle=connection_handle,
            peer_address=peer,
            role=PairingRole.INITIATOR,
            send=send,
        )
        ctx.local_io_caps = self._local_io_caps
        ctx.bondable = self._bondable
        ctx.local_address = self._local_address
        ctx._hci = self._hci
        ctx._bond_storage = self._bond_storage
        ctx.pairing_complete = asyncio.get_running_loop().create_future()
        register_transitions(ctx)
        self._contexts[connection_handle] = ctx
        await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
        return ctx.pairing_complete

    async def on_pdu(self, data: bytes, *, connection_handle: int) -> None:
        """Route an inbound SMP PDU to its connection's state machine."""
        if not data:
            return
        opcode = data[0]
        ctx = self._contexts.get(connection_handle)
        if ctx is None:
            if opcode != SMPCode.PAIRING_REQUEST:
                logger.debug(
                    "SMP PDU dropped: no context handle=0x%04X opcode=0x%02X",
                    connection_handle, opcode,
                )
                return
            send = self._senders.get(connection_handle)
            if send is None:
                logger.debug("SMP Pairing Request on unbound handle=0x%04X", connection_handle)
                return
            peer = self._peer_addrs.get(connection_handle, BDAddress(b"\x00" * 6))
            ctx = SMPPairingContext.create(
                connection_handle=connection_handle,
                peer_address=peer,
                role=PairingRole.RESPONDER,
                send=send,
            )
            ctx.local_io_caps = self._local_io_caps
            ctx.bondable = self._bondable
            ctx.local_address = self._local_address
            ctx._hci = self._hci
            ctx._bond_storage = self._bond_storage
            ctx.pairing_complete = asyncio.get_running_loop().create_future()
            from pybluehost.ble._smp_state import register_transitions
            register_transitions(ctx)
            self._contexts[connection_handle] = ctx

        pdu = decode_smp_pdu(data)
        event = _pdu_to_event(pdu)
        if event is None:
            logger.debug("Unhandled SMP opcode 0x%02X", opcode)
            return
        from pybluehost.core.errors import InvalidTransitionError
        try:
            await ctx.state_machine.fire(event, pdu=pdu)
        except InvalidTransitionError as e:
            logger.warning("SMP invalid transition: %s", e)
            try:
                await ctx.state_machine.fire(SMPEvent.PAIRING_FAILED_RX)
            except Exception:
                pass


def _pdu_to_event(pdu: SMPPdu) -> "SMPEvent | None":
    """Map an SMP PDU instance to the corresponding state-machine event."""
    from pybluehost.ble.smp import (
        SMPEncryptionInformation,
        SMPIdentityAddressInformation,
        SMPIdentityInformation,
        SMPMasterIdentification,
        SMPPairingConfirm,
        SMPPairingFailed,
        SMPPairingRandom,
        SMPPairingRequest,
        SMPPairingResponse,
        SMPSigningInformation,
    )
    if isinstance(pdu, SMPPairingRequest):
        return SMPEvent.PAIRING_REQ_RX
    if isinstance(pdu, SMPPairingResponse):
        return SMPEvent.PAIRING_RSP_RX
    if isinstance(pdu, SMPPairingConfirm):
        return SMPEvent.PAIRING_CONFIRM_RX
    if isinstance(pdu, SMPPairingRandom):
        return SMPEvent.PAIRING_RANDOM_RX
    if isinstance(pdu, SMPPairingFailed):
        return SMPEvent.PAIRING_FAILED_RX
    if isinstance(pdu, SMPEncryptionInformation):
        return SMPEvent.ENCRYPTION_INFO_RX
    if isinstance(pdu, SMPMasterIdentification):
        return SMPEvent.MASTER_IDENT_RX
    if isinstance(pdu, SMPIdentityInformation):
        return SMPEvent.IDENTITY_INFO_RX
    if isinstance(pdu, SMPIdentityAddressInformation):
        return SMPEvent.IDENTITY_ADDR_RX
    if isinstance(pdu, SMPSigningInformation):
        return SMPEvent.SIGNING_INFO_RX
    return None
