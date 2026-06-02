"""Tests for MITM SMP SC crypto primitives.

KAT vectors sourced from:
  - tests/unit/ble/test_smp.py  (BT Spec v5.4 sample data for f4/f5/f6/g2)
  - tests/unit/ble/test_smp_sc_crypto.py  (Core App D DHKey vector)
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from pybluehost.cli.app.mitm.pairing.crypto import (
    aes_cmac,
    dhkey,
    f4,
    f5,
    f6,
    g2,
    generate_keypair,
)


# ---------------------------------------------------------------------------
# aes_cmac
# ---------------------------------------------------------------------------

class TestAesCmac:
    def test_returns_16_bytes(self) -> None:
        key = bytes(16)
        result = aes_cmac(key, b"hello")
        assert isinstance(result, bytes)
        assert len(result) == 16

    def test_deterministic(self) -> None:
        key = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        msg = b"\x00" * 16
        assert aes_cmac(key, msg) == aes_cmac(key, msg)

    def test_rfc4493_vectors(self) -> None:
        """RFC 4493 AES-CMAC known-answer vectors (empty + 16-byte message)."""
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        assert aes_cmac(key, b"") == bytes.fromhex(
            "bb1d6929e95937287fa37d129b756746"
        )
        assert aes_cmac(key, bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")) == (
            bytes.fromhex("070a16b46b4d4144f79bdd9dd04a287c")
        )


# ---------------------------------------------------------------------------
# f4 — BT Spec v5.4 KAT (from tests/unit/ble/test_smp.py)
# ---------------------------------------------------------------------------

class TestF4:
    def test_spec_vector(self) -> None:
        """BT Spec v5.4 sample data for f4 (SC Confirm)."""
        U = bytes.fromhex(
            "20b003d2f297be2c5e2c83a7e9f9a5b9"
            "eff49111acf4fddbcc0301480e359de6"
        )
        V = bytes.fromhex(
            "55188b3d32f6bb9a900afcfbeed4e72a"
            "59cb9ac2f19d7cfb6b4fdd49f47fc5fd"
        )
        X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        Z = 0x00
        result = f4(U, V, X, Z)
        assert result == bytes.fromhex("f2c916f107a9bd1cf1eda1bea974872d")

    def test_returns_16_bytes(self) -> None:
        result = f4(bytes(32), bytes(32), bytes(16), 0)
        assert len(result) == 16


# ---------------------------------------------------------------------------
# f5 — BT Spec v5.4 KAT (from tests/unit/ble/test_smp.py)
# ---------------------------------------------------------------------------

class TestF5:
    def test_spec_vector(self) -> None:
        """BT Spec v5.4 sample data for f5 (SC Key Gen)."""
        W = bytes.fromhex(
            "ec0234a357c8ad05341010a60a397d9b"
            "99796b13b4f866f1868d34f373bfa698"
        )
        N1 = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        N2 = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        A1 = bytes.fromhex("00561237372600")
        A2 = bytes.fromhex("00a713702dcfc1")
        mac_key, ltk = f5(W, N1, N2, A1, A2)
        assert mac_key == bytes.fromhex("b6e4b4603eec848cbc64f040215bea5d")
        assert ltk == bytes.fromhex("30d519df60bb21fc43c81426c805fb83")

    def test_returns_two_16_byte_values(self) -> None:
        mac_key, ltk = f5(bytes(32), bytes(16), bytes(16), bytes(7), bytes(7))
        assert len(mac_key) == 16
        assert len(ltk) == 16
        assert mac_key != ltk


# ---------------------------------------------------------------------------
# f6 — BT Spec v5.4 KAT (from tests/unit/ble/test_smp.py)
# ---------------------------------------------------------------------------

class TestF6:
    def test_spec_vector(self) -> None:
        """BT Spec v5.4 sample data for f6 (SC DH-Key Check)."""
        W = bytes.fromhex("2965f176a1084a02fd3f6a20ce636e20")
        N1 = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        N2 = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        R = bytes.fromhex("12a3343bb453bb5408da42d20c2d0fc8")
        IOcap = bytes.fromhex("010002")
        A1 = bytes.fromhex("00561237372600")
        A2 = bytes.fromhex("00a713702dcfc1")
        result = f6(W, N1, N2, R, IOcap, A1, A2)
        assert result == bytes.fromhex("634d0cd5b6900432f0f741873863530a")

    def test_returns_16_bytes(self) -> None:
        result = f6(bytes(16), bytes(16), bytes(16), bytes(16), bytes(3), bytes(7), bytes(7))
        assert len(result) == 16


# ---------------------------------------------------------------------------
# g2 — BT Spec v5.4 KAT (from tests/unit/ble/test_smp.py)
# ---------------------------------------------------------------------------

class TestG2:
    def test_spec_vector(self) -> None:
        """BT Spec v5.4 sample data for g2 (SC Numeric Comparison)."""
        U = bytes.fromhex(
            "20b003d2f297be2c5e2c83a7e9f9a5b9"
            "eff49111acf4fddbcc0301480e359de6"
        )
        V = bytes.fromhex(
            "55188b3d32f6bb9a900afcfbeed4e72a"
            "59cb9ac2f19d7cfb6b4fdd49f47fc5fd"
        )
        X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        Y = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        result = g2(U, V, X, Y)
        assert result == 0x2F9ED5BA

    def test_returns_uint32(self) -> None:
        result = g2(bytes(32), bytes(32), bytes(16), bytes(16))
        assert isinstance(result, int)
        assert 0 <= result < 2**32


# ---------------------------------------------------------------------------
# generate_keypair / dhkey — Core App D vector
# (from tests/unit/ble/test_smp_sc_crypto.py)
# ---------------------------------------------------------------------------

class TestGenerateKeypair:
    def test_sizes(self) -> None:
        priv, pub = generate_keypair()
        assert len(priv) == 32
        assert len(pub) == 64

    def test_is_ephemeral(self) -> None:
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestDhkey:
    def test_symmetric_property(self) -> None:
        """ECDH(A_priv, B_pub) == ECDH(B_priv, A_pub)."""
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        dh_ab = dhkey(priv_a, pub_b)
        dh_ba = dhkey(priv_b, pub_a)
        assert dh_ab == dh_ba
        assert len(dh_ab) == 32

    def test_spec_test_vector(self) -> None:
        """Core 5.4 Vol 3 Part H Appendix D.5.6 (from tests/unit/ble/test_smp_sc_crypto.py).

        Initiator private (BE): 3f49f6d4a3c55f3874c9b3e3d2103f504aff607beb40b7995899b8a6cd3c1abd
        Responder private (BE): 55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd
        Expected DHKey (BE):    ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698
        """
        priv_a_be = bytes.fromhex(
            "3f49f6d4a3c55f3874c9b3e3d2103f504aff607beb40b7995899b8a6cd3c1abd"
        )
        priv_b_be = bytes.fromhex(
            "55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd"
        )
        priv_a_le = priv_a_be[::-1]

        # Derive B's public key in little-endian wire format
        sk_b = ec.derive_private_key(int.from_bytes(priv_b_be, "big"), ec.SECP256R1())
        pub_b_n = sk_b.public_key().public_numbers()
        pub_b_le = pub_b_n.x.to_bytes(32, "big")[::-1] + pub_b_n.y.to_bytes(32, "big")[::-1]

        result = dhkey(priv_a_le, pub_b_le)
        expected_be = bytes.fromhex(
            "ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698"
        )
        assert result == expected_be[::-1]

    def test_validates_sizes(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            dhkey(b"\x00" * 31, b"\x00" * 64)
        with pytest.raises(ValueError, match="64 bytes"):
            dhkey(b"\x00" * 32, b"\x00" * 63)
