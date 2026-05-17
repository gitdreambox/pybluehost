"""SecurityConfig and Cross-Transport Key Derivation (CTKD)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from pybluehost.ble.smp import SMPCrypto
from pybluehost.core.keys import LTK


# SSP shares the SMP logger namespace per the trace/log plan.
ssp_logger = logging.getLogger("pybluehost.ble.smp")


def _log_ssp_user_confirmation(*, handle: int, numeric_value: int) -> None:
    """Log an SSP user-confirmation request (numeric comparison)."""
    ssp_logger.info(
        "SSP user_confirmation handle=0x%04X numeric=%06d",
        handle, numeric_value,
    )


def _log_ssp_phase(*, handle: int, phase: str) -> None:
    """Log a transition into a particular SSP pairing phase."""
    ssp_logger.info("SSP phase=%s on handle=0x%04X", phase, handle)


@dataclass
class SecurityConfig:
    """SMP security configuration for a connection."""
    io_capability: int = 0x03       # NoInputNoOutput
    oob_flag: int = 0x00
    auth_requirements: int = 0x0D   # Bonding | MITM | SC
    max_key_size: int = 16
    initiator_keys: int = 0x01      # LTK
    responder_keys: int = 0x01      # LTK
    # NEW:
    enable_secure_connections: bool = False
    ctkd_enable: bool = False
    # Future hooks (commented stubs):
    # lea_enable: bool = False
    # le_security_mode: str = "1_2"
    # classic_security_mode: str = "4_2"
    # sc_only_mode: bool = False
    # iso_encryption_enable: bool = False
    # numeric_comparison_enable: bool = False


def _validate_sc_dependencies(cfg: "SecurityConfig") -> None:
    """Raise ConfigurationError if any SC-dependent feature is enabled without enable_secure_connections.

    Currently checks only CTKD. Future Plans add their own checks here.
    """
    from pybluehost.core.errors import ConfigurationError
    requires_sc: list[str] = []
    if cfg.ctkd_enable:
        requires_sc.append("CTKD")
    # Future hooks (commented stubs — uncomment when each feature lands):
    # if cfg.lea_enable:                          requires_sc.append("LE Audio")
    # if cfg.le_security_mode == "1_4":           requires_sc.append("LE Security Mode 1 Level 4")
    # if cfg.classic_security_mode == "4_4":      requires_sc.append("BR/EDR Security Mode 4 Level 4")
    # if cfg.sc_only_mode:                        requires_sc.append("Secure Connections Only Mode")
    # if cfg.iso_encryption_enable:               requires_sc.append("ISO Channel encryption")
    # if cfg.numeric_comparison_enable:           requires_sc.append("Numeric Comparison")
    if requires_sc and not cfg.enable_secure_connections:
        raise ConfigurationError(
            f"these features require enable_secure_connections=True: "
            f"{', '.join(requires_sc)}"
        )


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
