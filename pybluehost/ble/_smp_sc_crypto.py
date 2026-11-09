"""ECDH P-256 primitives for LE Secure Connections.

BT Core 5.4 Vol 3 Part H §2.3.5.6.1 defines SC pairing using P-256 ECDH.
Wire format is little-endian (LSB first); ``cryptography`` uses big-endian
internally. This module handles the byte-order conversion at the boundary.
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric import ec


def generate_p256_keypair() -> tuple[bytes, bytes]:
    """Generate an ephemeral P-256 keypair.

    Returns:
        (private_key, public_key):
        - private_key: 32 bytes, little-endian
        - public_key: 64 bytes = X (32 bytes LE) || Y (32 bytes LE)
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_value = private_key.private_numbers().private_value
    priv_be = priv_value.to_bytes(32, "big")
    pub_n = private_key.public_key().public_numbers()
    pub_x_be = pub_n.x.to_bytes(32, "big")
    pub_y_be = pub_n.y.to_bytes(32, "big")
    return priv_be[::-1], pub_x_be[::-1] + pub_y_be[::-1]


def peer_public_key_valid(peer_public: bytes) -> bool:
    """Return True if ``peer_public`` is a valid P-256 point (on the curve).

    BT Core Vol 3 Part H §2.3.5.6.1 / SM/*/KDU/BI-04: the IUT must reject an
    invalid peer public key (off-curve, (0,0), y=0, …) rather than compute a
    DHKey from it. ``cryptography`` raises ``ValueError`` for such points.

    Args:
        peer_public: 64-byte little-endian public point (X || Y).
    """
    if len(peer_public) != 64:
        return False
    peer_x = int.from_bytes(bytes(reversed(peer_public[:32])), "big")
    peer_y = int.from_bytes(bytes(reversed(peer_public[32:])), "big")
    try:
        ec.EllipticCurvePublicNumbers(peer_x, peer_y, ec.SECP256R1()).public_key()
    except ValueError:
        return False
    return True


def compute_dhkey(local_private: bytes, peer_public: bytes) -> bytes:
    """Compute DHKey = ECDH(local_private, peer_public).

    Args:
        local_private: 32-byte little-endian private scalar.
        peer_public: 64-byte little-endian public point (X || Y).

    Returns:
        DHKey: 32-byte little-endian shared X coordinate.
    """
    if len(local_private) != 32:
        raise ValueError(f"private key must be 32 bytes, got {len(local_private)}")
    if len(peer_public) != 64:
        raise ValueError(f"public key must be 64 bytes, got {len(peer_public)}")

    priv_be = bytes(reversed(local_private))
    peer_x_be = bytes(reversed(peer_public[:32]))
    peer_y_be = bytes(reversed(peer_public[32:]))

    priv_value = int.from_bytes(priv_be, "big")
    private_key = ec.derive_private_key(priv_value, ec.SECP256R1())

    peer_x = int.from_bytes(peer_x_be, "big")
    peer_y = int.from_bytes(peer_y_be, "big")
    peer_pub_n = ec.EllipticCurvePublicNumbers(peer_x, peer_y, ec.SECP256R1())
    peer_pub_key = peer_pub_n.public_key()

    shared = private_key.exchange(ec.ECDH(), peer_pub_key)
    return bytes(reversed(shared))
