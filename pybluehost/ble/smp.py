"""SMP (Security Manager Protocol) — pairing, crypto, and bond management."""
from __future__ import annotations

import json
import logging
import os
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Awaitable, Callable, Protocol, runtime_checkable

import asyncio

from pybluehost.core.address import AddressType, BDAddress
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


def _consume_future_exception(fut: "asyncio.Future[object]") -> None:
    if fut.cancelled():
        return
    try:
        fut.exception()
    except Exception:
        pass


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
PAIRING_FAILED_REASON_ENCRYPTION_KEY_SIZE   = 0x06
PAIRING_FAILED_REASON_UNSPECIFIED           = 0x08
PAIRING_FAILED_REASON_DHKEY_CHECK_FAILED    = 0x0B


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


@dataclass
class SMPPairingPublicKey(SMPPdu):
    """Pairing Public Key PDU (Core 5.4 Vol 3 Part H §3.5.6)."""
    public_key_x: bytes = b""
    public_key_y: bytes = b""

    def to_bytes(self) -> bytes:
        if len(self.public_key_x) != 32 or len(self.public_key_y) != 32:
            raise ValueError("public_key_x and public_key_y must each be 32 bytes")
        return bytes([SMPCode.PAIRING_PUBLIC_KEY]) + self.public_key_x + self.public_key_y

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingPublicKey:
        return cls(public_key_x=data[:32], public_key_y=data[32:64])


@dataclass
class SMPPairingDHKeyCheck(SMPPdu):
    """Pairing DHKey Check PDU (Core 5.4 Vol 3 Part H §3.5.7)."""
    dhkey_check: bytes = b""

    def to_bytes(self) -> bytes:
        if len(self.dhkey_check) != 16:
            raise ValueError("dhkey_check must be 16 bytes")
        return bytes([SMPCode.PAIRING_DHKEY_CHECK]) + self.dhkey_check

    @classmethod
    def from_bytes(cls, data: bytes) -> SMPPairingDHKeyCheck:
        return cls(dhkey_check=data[:16])


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
    SMPCode.PAIRING_PUBLIC_KEY: SMPPairingPublicKey,
    SMPCode.PAIRING_DHKEY_CHECK: SMPPairingDHKeyCheck,
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
        # Bluetooth SMP treats 128-bit values as little-endian. Keep this API in
        # on-air byte order and flip only at the AES block boundary.
        p1 = bytearray(16)
        p1[0] = int(iat)
        p1[1] = int(rat)
        p1[2:9] = preq
        p1[9:16] = pres

        # confirm = e(k, e(k, r XOR p1) XOR p2)
        # The SMP security function e() is little-endian for ALL of key, plaintext
        # and ciphertext (tinycrypt/zephyr aes_128 reverses all three at the AES
        # boundary). The data blocks are flipped inline here; the key must be
        # flipped too — with a zero TK (Just Works) that is a no-op, but for
        # Passkey Entry (non-zero TK) an unflipped key makes the peer reject our
        # confirm (Pairing Failed, 0x04 Confirm Value Failed).
        k = k[::-1]
        step1 = _aes_ecb(k, _xor(r[::-1], bytes(p1)[::-1]))
        p2 = b"\x00" * 4 + ia + ra
        return _aes_ecb(k, _xor(step1, p2))[::-1]

    @staticmethod
    def s1(k: bytes, r1: bytes, r2: bytes) -> bytes:
        """Legacy STK generation (BT Spec Vol 3 Part H §2.2.4).

        r' = r1[0:8] || r2[0:8] (least significant 8 bytes of each), result = e(k, r').
        """
        r_prime = r2[:8] + r1[:8]
        # Same little-endian e() convention as c1: flip the key at the AES boundary.
        return _aes_ecb(k[::-1], r_prime[::-1])[::-1]

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
            peer_address=BDAddress.from_string(
                entry["peer_address"],
                type=AddressType(entry.get("address_type", 0)),
            ),
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
                peer_address=BDAddress.from_string(
                    entry["peer_address"],
                    type=AddressType(entry.get("address_type", 0)),
                ),
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


class InMemoryBondStorage:
    """Volatile in-memory bond storage (no persistence across process restarts).

    Bonds live for the lifetime of the owning stack/SMP manager. Used by the
    PTS IUT (``app pts-tester``): a test case pairs, disconnects, and reconnects
    within a single pts-tester process, and the reconnection must be able to
    re-establish encryption from the bond stored during pairing. Without any
    storage the LTK is dropped at pairing time and the reconnect has nothing to
    encrypt with. A fresh pts-tester is spawned per test case, so in-memory
    storage gives a clean per-case slate — no cross-case bond leakage, unlike a
    file-backed store.
    """

    def __init__(self) -> None:
        self._bonds: dict[str, BondInfo] = {}

    async def save_bond(self, bond: BondInfo) -> None:
        self._bonds[str(bond.peer_address)] = bond

    async def load_bond(self, address: BDAddress) -> BondInfo | None:
        return self._bonds.get(str(address))

    async def delete_bond(self, address: BDAddress) -> None:
        self._bonds.pop(str(address), None)

    async def list_bonds(self) -> list[BondInfo]:
        return list(self._bonds.values())


# ---------------------------------------------------------------------------
# PairingDelegate Protocol + AutoAcceptDelegate
# ---------------------------------------------------------------------------

class PairingDelegate(Protocol):
    """User interaction interface for SMP pairing decisions."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool: ...
    async def confirm_passkey(self, peer_addr: BDAddress, passkey: int) -> bool: ...
    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool: ...
    async def get_passkey(self, peer_addr: BDAddress) -> int: ...
    async def display_passkey(self, peer_addr: BDAddress, passkey: int) -> None: ...


class AutoAcceptDelegate:
    """Default delegate that auto-accepts everything (for testing)."""

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, peer_addr: BDAddress, passkey: int) -> bool:
        return True

    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool:
        return True

    async def get_passkey(self, peer_addr: BDAddress) -> int:
        return 0

    async def display_passkey(self, peer_addr: BDAddress, passkey: int) -> None:
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
    PUBLIC_KEY_EXCHANGE     = 8
    DHKEY_CHECK             = 9
    NUMERIC_COMPARE_PENDING = 10
    PASSKEY_INPUT_PENDING   = 11
    PASSKEY_SC_ROUND        = 12


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
    PAIRING_PUBLIC_KEY_RX             = 16
    PAIRING_DHKEY_CHECK_RX            = 17
    NUMERIC_COMPARE_USER_CONFIRMED    = 18
    NUMERIC_COMPARE_USER_REJECTED     = 19
    PASSKEY_USER_ENTERED              = 20
    PASSKEY_USER_REJECTED             = 21


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
    pending_phase3_pdus: list[tuple["SMPEvent", SMPPdu]] = field(default_factory=list)

    # SC working state (Sub-Plan 2)
    local_private_key: bytes = b""
    local_public_key: bytes = b""
    peer_public_key: bytes = b""
    dhkey: bytes = b""
    mac_key: bytes = b""
    ltk_sc: bytes = b""
    local_dhkey_check: bytes = b""
    peer_dhkey_check: bytes = b""

    # Legacy OOB (Sub-Plan 3c): a 16-byte TK provisioned out-of-band. Empty =
    # no OOB data. When set, the pairing uses this as the TK (instead of 0 for
    # Just Works) and advertises oob_data_flag=1 in the feature exchange.
    oob_tk: bytes = b""

    # LE Secure Connections OOB (§2.3.5.6.4). ``oob_sc_keypair`` is the cached
    # (priv, pub) the local OOB confirm commits to (reused as the over-the-air
    # keypair); ``oob_sc_local_rand``/``oob_sc_remote_rand``/``oob_sc_remote_conf``
    # are the OOB randoms / peer confirm. Empty = that side has no OOB data.
    oob_sc_keypair: tuple[bytes, bytes] | None = None
    oob_sc_local_rand: bytes = b""
    oob_sc_remote_rand: bytes = b""
    oob_sc_remote_conf: bytes = b""
    peer_oob_data_flag: int = 0

    # Bookkeeping
    bondable: bool = True
    local_address: BDAddress | None = None  # On-air address for c1/f5/f6.
    local_identity_address: BDAddress | None = None  # Stable IdKey address.
    pairing_complete: "asyncio.Future[None] | None" = None
    send: "Callable[[bytes], Awaitable[None]] | None" = None
    _hci: object | None = None
    _bond_storage: "BondStorage | None" = None
    security_config: object | None = None  # SecurityConfig (avoid import cycle)

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

    _VALID_PTS_FAILURE_STAGES = frozenset({
        "pairing_request", "pairing_response",
        "confirm_value", "random_value", "key_distribution",
    })

    def __init__(
        self,
        hci: object | None = None,
        bond_storage: BondStorage | None = None,
        delegate: PairingDelegate | AutoAcceptDelegate | None = None,
        local_io_caps: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT,
        bondable: bool = True,
        local_address: BDAddress | None = None,
        security_config: object | None = None,  # SecurityConfig
    ) -> None:
        self._hci = hci
        self._bond_storage = bond_storage
        # Optional callable returning the peer BDAddress for a connection
        # handle; used to look up an existing bond when a Security Request
        # arrives (see on_pdu).
        self._peer_address_provider: Callable[[int], object] | None = None
        # Optional async callable (handle, bond) -> None that starts LL
        # encryption from an existing bond. Wired by Stack; used when a Security
        # Request asks for a level the stored bond already provides, where the
        # peer means "encrypt with that LTK", not "pair again".
        self._bond_resume: Callable[[int, object], Awaitable[None]] | None = None
        self._delegate = delegate or AutoAcceptDelegate()
        self._local_io_caps = local_io_caps
        self._bondable = bondable
        self._local_address = local_address
        self._security_config = security_config
        self._senders: dict[int, Callable[[bytes], Awaitable[None]]] = {}
        self._peer_addrs: dict[int, BDAddress] = {}
        # Per-connection address we used on air when it is not the identity
        # (host-programmed RPA/NRPA advertising or initiating). f5/f6 and the
        # legacy c1 hash the on-air addresses, so the peer's DHKey Check only
        # matches when we use the same RPA it saw in its connection event
        # (GAP/PRIV/CONN/BV-10-C).
        self._local_addrs: dict[int, BDAddress] = {}
        self._local_irk_cache: bytes | None = None
        self._local_irk_override: bytes | None = None
        self._contexts: dict[int, SMPPairingContext] = {}
        self._oob_legacy_tk: bytes = b""
        # LE Secure Connections OOB (Core Vol 3 Part H §2.3.5.6.4). The local
        # block is generated lazily on the first BTP OOB_SC_GET_LOCAL_DATA and
        # cached so WID 147 (returns Conf) and WID 148 (returns Rand) hand PTS a
        # consistent (r, C) pair, and so the SAME P-256 keypair that C commits
        # to is the one we send over the air during pairing.
        self._oob_sc_local: dict[str, bytes] | None = None
        self._oob_sc_remote: tuple[bytes, bytes] | None = None  # (rand, conf)
        # Listeners invoked when a pairing fails — crucially when the PEER aborts
        # with a Pairing Failed PDU (a responder has no pair() waiter to surface
        # it). BTP GAP subscribes to emit PAIRING_FAILED (SM/*/KDU/BI-02/03).
        self._pairing_failed_cbs: list = []
        # Handles this manager sent a Security Request on, until the channel
        # unbinds. A Pairing Request arriving while the mark is set means the
        # central had no usable bond for us (a bonded central answers the
        # request by encrypting, §3.6.1) — the lost-bond signal for BV-22.
        self._secreq_sent: set[int] = set()
        # Listeners invoked when the peer's bond turns out to be gone. The
        # Stack bridges these into its own bond-lost path (BTP BOND_LOST).
        self._bond_lost_cbs: list = []

    def on_bond_lost(self, callback) -> None:
        """Register ``callback(connection_handle, peer_address)`` fired when the
        peer responds to our Security Request with a Pairing Request while we
        still hold a bond — i.e. the peer lost its half of the bond."""
        self._bond_lost_cbs.append(callback)

    def _emit_bond_lost(self, connection_handle: int) -> None:
        peer = self._peer_addrs.get(connection_handle)
        for cb in self._bond_lost_cbs:
            try:
                cb(connection_handle, peer)
            except Exception:  # noqa: BLE001
                logger.exception("bond_lost callback raised")

    def on_pairing_failed(self, callback) -> None:
        """Register ``callback(connection_handle, peer_address, reason)`` fired when
        a pairing fails, including when the peer aborts with a Pairing Failed PDU."""
        self._pairing_failed_cbs.append(callback)

    def _emit_pairing_failed(self, connection_handle: int, reason: int) -> None:
        peer = self._peer_addrs.get(connection_handle)
        for cb in self._pairing_failed_cbs:
            try:
                cb(connection_handle, peer, reason)
            except Exception:  # noqa: BLE001
                logger.exception("pairing_failed callback raised")

    @property
    def local_irk(self) -> bytes:
        """This device's Identity Resolving Key.

        Stable for the lifetime of the stack and distributed to the peer in the
        pairing key-distribution phase (Identity Information). The privacy
        manager uses it to build the resolvable private addresses the peer is
        expected to be able to resolve.

        ``set_local_irk`` pins it to a known value — the PTS IUT publishes the
        same key as the ``TSPX_iut_device_IRK_...`` PIXIT so the Lower Tester
        can resolve the RPAs the IUT advertises (GAP/BROB/BCST/BV-03).
        """
        if self._local_irk_override is not None:
            return self._local_irk_override
        if self._local_irk_cache is None:
            self._local_irk_cache = os.urandom(16)
        return self._local_irk_cache

    def set_local_irk(self, irk: bytes) -> None:
        """Pin the local IRK (must be published as the matching PIXIT)."""
        self._local_irk_override = bytes(irk[:16]).ljust(16, b"\x00")

    def bind_channel(
        self,
        connection_handle: int,
        send: Callable[[bytes], Awaitable[None]],
        peer_address: BDAddress | None = None,
    ) -> None:
        """Bind an L2CAP CID_SMP send-callable to a connection handle."""
        _orig_send = send

        async def _logging_send(data: bytes) -> None:
            logger.debug("SMP TX handle=0x%04X %s", connection_handle, data.hex())
            await _orig_send(data)

        self._senders[connection_handle] = _logging_send
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

    def register_local_address(
        self, connection_handle: int, address: BDAddress
    ) -> None:
        """Bind the address this link uses on air when it is a random one.

        The controller's Connection Complete never reports a host-programmed
        random address, while the peer hashes exactly the address it saw in its
        own connection event. Stack therefore hands the programmed address over
        here; the pairing context for that handle uses it for f5/f6 (and the
        legacy c1) instead of the public identity.
        """
        self._local_addrs[connection_handle] = address

    def unbind_channel(self, connection_handle: int) -> None:
        """Remove the L2CAP send-callable and tear down any active context."""
        self._senders.pop(connection_handle, None)
        self._peer_addrs.pop(connection_handle, None)
        self._local_addrs.pop(connection_handle, None)
        self._secreq_sent.discard(connection_handle)
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

    def _sc_only_active(self) -> bool:
        """True when Secure Connections Only mode is enforced (BTP GAP
        SET_SC_ONLY / SecurityConfig.sc_only_mode). Legacy (non-SC) pairing
        attempts are rejected with Pairing Failed 0x03."""
        cfg = self._security_config
        return bool(cfg is not None and getattr(cfg, "sc_only_mode", False))

    def set_bondable(self, bondable: bool) -> None:
        """Update the bonding flag used in subsequent Pairing Request/Response.

        PTS SM tests toggle this per-case via BTP GAP SET_BONDABLE (e.g.
        SM/CEN/JW/BV-01-C requires AuthReq Bonding Flags = 0x00); it must reach
        the SMP layer, not just GAP settings bookkeeping.
        """
        self._bondable = bondable

    def set_oob_legacy_data(self, oob_tk: bytes) -> None:
        """Provision the 16-byte legacy OOB TK for subsequent pairings.

        PTS SM/*/OOB tests push this via BTP GAP OOB_LEGACY_SET_DATA (0x18).
        When set, the pairing feature exchange advertises oob_data_flag=1 and
        the legacy path uses this TK (both devices share the OOB data) instead
        of the Just Works all-zero TK.
        """
        self._oob_legacy_tk = bytes(oob_tk)

    # ---- LE Secure Connections OOB (§2.3.5.6.4) ----

    def get_oob_sc_local_data(self) -> tuple[bytes, bytes]:
        """Return the local SC OOB ``(rand, conf)`` pair, generating it lazily.

        C = f4(PKx, PKx, r, 0) commits to our own P-256 public key X coordinate,
        so the keypair generated here is cached and REUSED as the over-the-air
        pairing keypair — otherwise the confirm we hand PTS would not match the
        public key we later send. Idempotent per process so the auto-pts WID 147
        (Conf) and WID 148 (Rand) calls return a consistent pair.
        """
        if self._oob_sc_local is None:
            import os

            from pybluehost.ble._smp_sc_crypto import generate_p256_keypair
            from pybluehost.ble._smp_state import _sc_f4

            priv, pub = generate_p256_keypair()
            rand = os.urandom(16)
            conf = _sc_f4(pub[:32], pub[:32], rand, 0)
            self._oob_sc_local = {
                "priv": priv, "pub": pub, "rand": rand, "conf": conf,
            }
        return self._oob_sc_local["rand"], self._oob_sc_local["conf"]

    def set_oob_sc_remote_data(self, rand: bytes, conf: bytes) -> None:
        """Store the peer's SC OOB ``(rand, conf)`` (BTP OOB_SC_SET_REMOTE_DATA).

        During SC pairing we verify the peer's over-the-air public key against
        this confirm and use ``rand`` as the peer's OOB random input to f6.
        """
        self._oob_sc_remote = (bytes(rand), bytes(conf))

    def _apply_oob_sc(self, ctx: "SMPPairingContext") -> None:
        """Copy any provisioned SC OOB data onto a fresh pairing context."""
        if self._oob_sc_local is not None:
            ctx.oob_sc_keypair = (
                self._oob_sc_local["priv"], self._oob_sc_local["pub"],
            )
            ctx.oob_sc_local_rand = self._oob_sc_local["rand"]
        if self._oob_sc_remote is not None:
            ctx.oob_sc_remote_rand, ctx.oob_sc_remote_conf = self._oob_sc_remote

    def get_context(self, connection_handle: int) -> SMPPairingContext | None:
        return self._contexts.get(connection_handle)

    async def request_security(self, connection_handle: int, *, auth_req: int = 0x01) -> None:
        """Send Security Request as LE peripheral to ask the central to pair."""
        send = self._senders.get(connection_handle)
        if send is None:
            raise RuntimeError(f"No SMP channel bound for handle=0x{connection_handle:04X}")
        await send(SMPSecurityRequest(auth_req=auth_req).to_bytes())
        self._secreq_sent.add(connection_handle)

    async def request_security_and_wait(
        self, connection_handle: int, *, auth_req: int = 0x01, timeout: float = 30.0
    ) -> None:
        """Peripheral pairing: send a Security Request, then wait for the central
        to pair (the responder context created by its Pairing Request).

        If a pairing is already in flight on this handle — the central initiated
        it, e.g. answering our earlier Security Request — sending another
        Security Request would interrupt the peer's pairing (it answers with
        Pairing Failed), so we just wait for the existing context instead.

        Resolves when that pairing completes; raises RuntimeError on timeout and
        propagates any pairing-failure exception from the responder path.
        """
        existing = self._contexts.get(connection_handle)
        if existing is not None and existing.state_machine.state != SMPState.FAILED:
            remaining = timeout
        else:
            await self.request_security(connection_handle, auth_req=auth_req)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            ctx = self._contexts.get(connection_handle)
            while ctx is None:
                if loop.time() >= deadline:
                    raise RuntimeError(
                        f"Pairing (peripheral) timeout on handle=0x{connection_handle:04X}")
                await asyncio.sleep(0.01)
                ctx = self._contexts.get(connection_handle)
            remaining = max(0.01, deadline - loop.time())
            existing = ctx
        # Shield so a wait_for timeout doesn't cancel the shared completion future.
        await asyncio.wait_for(asyncio.shield(existing.pairing_complete), timeout=remaining)

    async def start_initiator(
        self, connection_handle: int, *, peer_sec_req_auth_req: int | None = None
    ) -> "asyncio.Future[None]":
        """Begin Initiator-role pairing on a connected LE link.

        ``peer_sec_req_auth_req`` carries the AuthReq from a peer's Security
        Request (when pairing is triggered by it rather than a local pair()); its
        MITM bit is mirrored into the Pairing Request so the negotiated security
        level matches what the peripheral asked for. ``None`` (the default) marks
        a locally-initiated pair(), whose MITM bit comes from the security config.
        """
        from pybluehost.ble._smp_state import register_transitions
        existing = self._contexts.get(connection_handle)
        if existing is not None \
                and existing.state_machine.state not in (SMPState.BONDED, SMPState.FAILED):
            raise RuntimeError(f"SMP context already active for handle=0x{connection_handle:04X}")
        if existing is not None:
            # A finished context (BONDED / FAILED) is replaced by the fresh
            # pairing — the SecReq path above already does exactly this, and
            # the repair pairing after a failed bond resume (GAP.TS 4.7.5.1.x)
            # lands right after the preamble pairing completed.
            self._contexts.pop(connection_handle, None)
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
        ctx.local_identity_address = self._local_address
        ctx.local_io_caps = self._local_io_caps
        ctx.bondable = self._bondable
        ctx.local_address = self._local_addrs.get(
            connection_handle, self._local_address
        )
        ctx._hci = self._hci
        ctx._bond_storage = self._bond_storage
        ctx.security_config = self._security_config
        ctx._delegate = self._delegate
        ctx.peer_sec_req_auth_req = peer_sec_req_auth_req
        ctx.oob_tk = self._oob_legacy_tk
        ctx._smp_manager = self
        self._apply_oob_sc(ctx)
        ctx.pairing_complete = asyncio.get_running_loop().create_future()
        # Consume a failure when the future goes unawaited (Security-Request
        # initiated pairing discards the return value) to avoid the "exception
        # was never retrieved" warning.
        ctx.pairing_complete.add_done_callback(_consume_future_exception)
        register_transitions(ctx)
        self._contexts[connection_handle] = ctx
        await ctx.state_machine.fire(SMPEvent.LOCAL_PAIR_REQUEST)
        return ctx.pairing_complete

    def set_peer_address_provider(self, provider: Callable[[int], object]) -> None:
        """Register ``provider(handle) -> BDAddress | None`` so a Security
        Request can be checked against an existing bond."""
        self._peer_address_provider = provider

    def set_bond_resume_handler(
        self, handler: Callable[[int, object, int], Awaitable[None]],
    ) -> None:
        """Register ``handler(handle, bond, auth_req)`` to start LL encryption.

        ``auth_req`` is the peer Security Request's requested level; the stack
        reuses it when the resume attempt fails and a fresh authenticated
        pairing (mirroring that level) is the only way forward.
        """
        self._bond_resume = handler

    def _bond_covers(self, bond: "BondInfo", auth_req: int) -> bool:
        """True if the stored bond already provides what ``auth_req`` asks for.

        Only the bits a bond can actually deliver are checked: an
        unauthenticated bond cannot answer a MITM request, and a legacy bond
        cannot answer a Secure-Connections request. In either case the peer
        really does need a fresh pairing (PTS GAP/SEC/AUT/BV-13 pairs Just
        Works and then asks for MITM). When the bond already covers the request
        the peer just wants the link encrypted with that LTK.
        """
        if auth_req & 0x04 and not bond.authenticated:
            return False
        if auth_req & 0x08 and not bond.sc:
            return False
        return True

    async def _stored_bond_for(self, handle: int) -> "BondInfo | None":
        storage = self._bond_storage
        if storage is None or self._peer_address_provider is None:
            return None
        peer = self._peer_address_provider(handle)
        if peer is None:
            return None
        try:
            bond = await storage.load_bond(peer)
        except Exception:
            logger.exception("SMP: bond lookup failed handle=0x%04X", handle)
            return None
        return bond

    async def on_pdu(self, data: bytes, *, connection_handle: int) -> None:
        """Route an inbound SMP PDU to its connection's state machine."""
        if not data:
            return
        logger.debug("SMP RX handle=0x%04X %s", connection_handle, data.hex())
        opcode = data[0]
        ctx = self._contexts.get(connection_handle)
        # A Security Request is meaningful both before any pairing and *after*
        # one finished: the peer asks for a level the current link does not meet
        # yet (PTS GAP/SEC/AUT/BV-13 pairs Just Works, then sends a Security
        # Request with MITM to force an authenticated pairing). A finished
        # context is dropped so the fresh pairing can start — otherwise the PDU
        # fell through to "Unhandled SMP opcode 0x0B" and PTS gave up with
        # Pairing Failed (Core Vol 3 Part H §3.6.1).
        if (
            opcode == SMPCode.SECURITY_REQUEST
            and ctx is not None
            and ctx.state_machine.state in (SMPState.BONDED, SMPState.FAILED)
        ):
            self._contexts.pop(connection_handle, None)
            ctx = None
        if ctx is None:
            if opcode == SMPCode.SECURITY_REQUEST:
                # LE central: the peripheral's Security Request asks us to
                # initiate pairing (Core Vol 3 Part H §3.6.1). Honor the peer's
                # requested security level (e.g. MITM for authenticated pairing)
                # so the link reaches the mode the test requires — PTS
                # GAP/SEC/AUT reads a protected char, gets Insufficient
                # Authentication, then sends this expecting us to pair.
                try:
                    sec_pdu = decode_smp_pdu(data)
                    hint = getattr(sec_pdu, "auth_req", 0)
                    # SC-only mode (GAP/SEC/SEM/BV-29): reject a Security
                    # Request from an SC-incapable peer with Pairing Failed
                    # "Authentication Requirements" — legacy pairing must not
                    # even start.
                    if self._sc_only_active() and not (hint & 0x08):
                        send = self._senders.get(connection_handle)
                        if send is not None:
                            await send(SMPPairingFailed(reason=0x03).to_bytes())
                        return
                    # An existing bond that already meets the requested level
                    # means the peer wants the link *encrypted* with that LTK,
                    # not a fresh pairing. Pairing anyway leaves PTS (which is
                    # not prepared to pair again) silent and the case dies on our
                    # 30 s timeout — the on-air trace is a lone Pairing Request
                    # with no response (GAP/BROB/BCST/BV-03, GAP/BOND/BON/BV-04).
                    bond = await self._stored_bond_for(connection_handle)
                    covered = bond is not None and bool(bond.ltk) \
                        and self._bond_covers(bond, hint)
                    logger.info(
                        "SMP: Security Request auth_req=0x%02X handle=0x%04X "
                        "bond=%s covers=%s",
                        hint, connection_handle,
                        "none" if bond is None else "yes", covered,
                    )
                    if covered:
                        # The peer wants the link *encrypted* with the bond it
                        # already shares, not a fresh pairing. Starting the LL
                        # encryption procedure is the whole point of the request
                        # (GAP/SEC/AUT/BV-13 step 2: "The IUT initiates and
                        # completes the encryption of the link"). Pairing instead
                        # leaves PTS silent and the case dies on our 30 s timeout;
                        # merely returning (the previous behaviour) left the link
                        # unencrypted, so the LT's next protected access never got
                        # the Insufficient-Authentication response the case needs.
                        if self._bond_resume is not None:
                            await self._bond_resume(connection_handle, bond, hint)
                        return
                    await self.start_initiator(
                        connection_handle, peer_sec_req_auth_req=hint)
                except Exception:
                    logger.exception(
                        "SMP failed to start pairing on Security Request handle=0x%04X",
                        connection_handle,
                    )
                return
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
            ctx.local_identity_address = self._local_address
            ctx.local_io_caps = self._local_io_caps
            ctx.bondable = self._bondable
            ctx.local_address = self._local_addrs.get(
            connection_handle, self._local_address
        )
            ctx._hci = self._hci
            ctx._bond_storage = self._bond_storage
            ctx.security_config = self._security_config
            ctx._delegate = self._delegate
            ctx.oob_tk = self._oob_legacy_tk
            ctx._smp_manager = self
            self._apply_oob_sc(ctx)
            ctx.pairing_complete = asyncio.get_running_loop().create_future()
            ctx.pairing_complete.add_done_callback(_consume_future_exception)
            from pybluehost.ble._smp_state import register_transitions
            register_transitions(ctx)
            self._contexts[connection_handle] = ctx

        pdu = decode_smp_pdu(data)
        event = _pdu_to_event(pdu)
        if event is None:
            logger.debug("Unhandled SMP opcode 0x%02X", opcode)
            return
        if _should_defer_phase3_pdu(ctx, event):
            ctx.pending_phase3_pdus.append((event, pdu))
            logger.debug(
                "SMP deferred Phase 3 %s while state=%s handle=0x%04X",
                event.name, ctx.state_machine.state.name, connection_handle,
            )
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
        SMPPairingDHKeyCheck,
        SMPPairingFailed,
        SMPPairingPublicKey,
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
    if isinstance(pdu, SMPPairingPublicKey):
        return SMPEvent.PAIRING_PUBLIC_KEY_RX
    if isinstance(pdu, SMPPairingDHKeyCheck):
        return SMPEvent.PAIRING_DHKEY_CHECK_RX
    return None


def _should_defer_phase3_pdu(ctx: SMPPairingContext, event: "SMPEvent") -> bool:
    if event not in {
        SMPEvent.ENCRYPTION_INFO_RX,
        SMPEvent.MASTER_IDENT_RX,
        SMPEvent.IDENTITY_INFO_RX,
        SMPEvent.IDENTITY_ADDR_RX,
        SMPEvent.SIGNING_INFO_RX,
    }:
        return False
    return ctx.state_machine.state in {
        SMPState.RANDOM_EXCHANGE,
        SMPState.STK_ENCRYPTING,
        SMPState.DHKEY_CHECK,
    }
