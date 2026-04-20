"""Tests for SecurityConfig and CTKDManager."""
from __future__ import annotations

from pybluehost.ble.security import SecurityConfig, CTKDDirection, CTKDManager
from pybluehost.core.keys import LTK


def test_security_config_defaults():
    cfg = SecurityConfig()
    assert cfg.io_capability == 0x03       # NoInputNoOutput
    assert cfg.oob_flag == 0x00
    assert cfg.auth_requirements == 0x0D   # Bonding | MITM | SC
    assert cfg.max_key_size == 16
    assert cfg.initiator_keys == 0x01
    assert cfg.responder_keys == 0x01


def test_ctkd_direction_enum():
    assert CTKDDirection.LE_TO_BREDR == "le_to_bredr"
    assert CTKDDirection.BREDR_TO_LE == "bredr_to_le"


def test_derive_link_key_from_ltk():
    """BT Core Spec 5.3 Vol 3 Part H §3.6.1 — LE LTK → BR/EDR link key."""
    ltk = LTK(
        value=bytes.fromhex("ec0234a357c8ad05341010a60a397d9b"),
        rand=bytes(8), ediv=0,
    )
    link_key = CTKDManager.derive_link_key_from_ltk(ltk)
    assert len(link_key) == 16


def test_derive_ltk_from_link_key():
    """BT Core Spec 5.3 Vol 3 Part H §3.6.1 — BR/EDR link key → LE LTK."""
    link_key = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    ltk = CTKDManager.derive_ltk_from_link_key(link_key)
    assert isinstance(ltk, LTK)
    assert len(ltk.value) == 16


def test_ctkd_deterministic():
    """Derivation is deterministic: same input → same output."""
    ltk = LTK(
        value=bytes.fromhex("ec0234a357c8ad05341010a60a397d9b"),
        rand=bytes(8), ediv=0,
    )
    lk1 = CTKDManager.derive_link_key_from_ltk(ltk)
    lk2 = CTKDManager.derive_link_key_from_ltk(ltk)
    assert lk1 == lk2


def test_derive_link_key_uses_h7_h6():
    """Verify link key derivation uses h7 then h6 (spec chain)."""
    from pybluehost.ble.smp import SMPCrypto

    ltk_bytes = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
    ltk = LTK(value=ltk_bytes, rand=bytes(8), ediv=0)

    # Manual computation: ilk = h7(SALT_TMP2, LTK), link_key = h6(ilk, "lebr")
    SALT_TMP2 = bytes.fromhex("31703ef27b8ac9c44fef1b50ac8b51c3")
    ilk = SMPCrypto.h7(SALT_TMP2, ltk_bytes)
    expected_lk = SMPCrypto.h6(ilk, b"lebr")

    result = CTKDManager.derive_link_key_from_ltk(ltk)
    assert result == expected_lk
