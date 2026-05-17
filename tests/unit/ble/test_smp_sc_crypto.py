"""ECDH P-256 keypair + DHKey tests with Core 5.4 Vol 3 Part H App D test vector."""
from __future__ import annotations

import pytest

from pybluehost.ble._smp_sc_crypto import compute_dhkey, generate_p256_keypair


def test_keypair_sizes():
    priv, pub = generate_p256_keypair()
    assert len(priv) == 32
    assert len(pub) == 64  # X (32) || Y (32) each LE


def test_keypair_is_ephemeral():
    priv1, pub1 = generate_p256_keypair()
    priv2, pub2 = generate_p256_keypair()
    assert priv1 != priv2
    assert pub1 != pub2


def test_dhkey_symmetric_property():
    """ECDH(A_priv, B_pub) == ECDH(B_priv, A_pub)."""
    priv_a, pub_a = generate_p256_keypair()
    priv_b, pub_b = generate_p256_keypair()
    dhkey_ab = compute_dhkey(priv_a, pub_b)
    dhkey_ba = compute_dhkey(priv_b, pub_a)
    assert dhkey_ab == dhkey_ba
    assert len(dhkey_ab) == 32


def test_dhkey_spec_test_vector():
    """Core 5.4 Vol 3 Part H Appendix D.5.6.

    Initiator private (BE from spec):  3f49f6d4a3c55f3874c9b3e3d2103f504aff607beb40b7995899b8a6cd3c1abd
    Responder private (BE):            55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd
    Expected DHKey (BE):               ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698

    Our API takes/returns little-endian per BT spec.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    priv_a_be = bytes.fromhex("3f49f6d4a3c55f3874c9b3e3d2103f504aff607beb40b7995899b8a6cd3c1abd")
    priv_b_be = bytes.fromhex("55188b3d32f6bb9a900afcfbeed4e72a59cb9ac2f19d7cfb6b4fdd49f47fc5fd")
    priv_a = priv_a_be[::-1]

    # Derive B's public key for use with our compute_dhkey API
    sk_b = ec.derive_private_key(int.from_bytes(priv_b_be, "big"), ec.SECP256R1())
    pub_b_n = sk_b.public_key().public_numbers()
    pub_b_x_be = pub_b_n.x.to_bytes(32, "big")
    pub_b_y_be = pub_b_n.y.to_bytes(32, "big")
    pub_b_le = pub_b_x_be[::-1] + pub_b_y_be[::-1]

    dhkey = compute_dhkey(priv_a, pub_b_le)
    expected_be = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b99796b13b4f866f1868d34f373bfa698")
    assert dhkey == expected_be[::-1], (
        f"DHKey mismatch:\n got  {dhkey.hex()}\n want {expected_be[::-1].hex()}"
    )


def test_compute_dhkey_validates_sizes():
    with pytest.raises(ValueError, match="32 bytes"):
        compute_dhkey(b"\x00" * 31, b"\x00" * 64)
    with pytest.raises(ValueError, match="64 bytes"):
        compute_dhkey(b"\x00" * 32, b"\x00" * 63)
