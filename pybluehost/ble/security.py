"""SecurityConfig and Cross-Transport Key Derivation (CTKD)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pybluehost.ble.smp import SMPCrypto
from pybluehost.core.keys import LTK


@dataclass
class SecurityConfig:
    """SMP security configuration for a connection."""
    io_capability: int = 0x03       # NoInputNoOutput
    oob_flag: int = 0x00
    auth_requirements: int = 0x0D   # Bonding | MITM | SC
    max_key_size: int = 16
    initiator_keys: int = 0x01      # LTK
    responder_keys: int = 0x01      # LTK


class CTKDDirection(str, Enum):
    """Direction of Cross-Transport Key Derivation."""
    LE_TO_BREDR = "le_to_bredr"
    BREDR_TO_LE = "bredr_to_le"


class CTKDManager:
    """Cross-Transport Key Derivation per BT Core Spec 5.3 Vol 3 Part H §3.6.1."""

    # SALTs from spec
    _SALT_TMP1 = bytes.fromhex("000000000000000000000000746D7031")  # "tmp1"
    _SALT_TMP2 = bytes.fromhex("31703ef27b8ac9c44fef1b50ac8b51c3")

    @staticmethod
    def derive_link_key_from_ltk(ltk: LTK) -> bytes:
        """Derive BR/EDR Link Key from LE LTK.

        ilk = h7(SALT_TMP2, LTK); link_key = h6(ilk, "lebr")
        """
        ilk = SMPCrypto.h7(CTKDManager._SALT_TMP2, ltk.value)
        return SMPCrypto.h6(ilk, b"lebr")

    @staticmethod
    def derive_ltk_from_link_key(link_key: bytes) -> LTK:
        """Derive LE LTK from BR/EDR Link Key.

        ilk = h7(SALT_TMP1, link_key); ltk_key = h6(ilk, "brle")
        """
        ilk = SMPCrypto.h7(CTKDManager._SALT_TMP1, link_key)
        key = SMPCrypto.h6(ilk, b"brle")
        return LTK(value=key, rand=bytes(8), ediv=0)
