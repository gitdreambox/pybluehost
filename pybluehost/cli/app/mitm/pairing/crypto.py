"""SMP Secure Connections crypto primitives for the MITM app.

Self-contained port of the verified implementations in:
  - pybluehost/ble/smp.py   (f4, f5, f6, g2)
  - pybluehost/ble/_smp_sc_crypto.py  (generate_keypair, dhkey)

No imports from pybluehost.ble.* — the MITM must stay self-contained.
Only stdlib (struct) and ``cryptography`` are used.

Sync note: this is a deliberate port. If pybluehost/ble/smp.py (SMPCrypto) or
_smp_sc_crypto.py change, mirror the change here.

ECDH wire format is little-endian (BT Core 5.4 Vol 3 Part H §2.3.5.6.1);
byte-order is reversed at the cryptography-library boundary.
"""
from __future__ import annotations

import struct

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.cmac import CMAC

# f5 SALT (BT Spec Vol 3 Part H §2.2.7).
_F5_SALT = bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _cmac(key: bytes, message: bytes) -> bytes:
    c = CMAC(algorithms.AES(key))
    c.update(message)
    return c.finalize()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aes_cmac(key: bytes, msg: bytes) -> bytes:
    """AES-CMAC (BT Spec Vol 3 Part H §2.2.5)."""
    return _cmac(key, msg)


def f4(u: bytes, v: bytes, x: bytes, z: int) -> bytes:
    """SC confirm value (BT Spec Vol 3 Part H §2.2.6).

    f4(U, V, X, Z) = AES-CMAC_X(U || V || Z)

    Args:
        u: 32-byte X coordinate of the initiator public key (PKa_x).
        v: 32-byte X coordinate of the responder public key (PKb_x).
        x: 16-byte key (a nonce).
        z: 1-byte integer.
    """
    return _cmac(x, u + v + bytes([z]))


def f5(
    w: bytes,
    n1: bytes,
    n2: bytes,
    a1: bytes,
    a2: bytes,
) -> tuple[bytes, bytes]:
    """SC key generation (BT Spec Vol 3 Part H §2.2.7).

    Returns:
        (MacKey, LTK) each 16 bytes.
    """
    T = _cmac(_F5_SALT, w)
    key_id = b"btle"            # keyID = "btle" in ASCII
    length = b"\x01\x00"        # Length = 256, 2-byte big-endian

    # MacKey = AES-CMAC_T(0x00 || keyID || N1 || N2 || A1 || A2 || Length)
    mac_key = _cmac(T, bytes([0x00]) + key_id + n1 + n2 + a1 + a2 + length)
    # LTK    = AES-CMAC_T(0x01 || keyID || N1 || N2 || A1 || A2 || Length)
    ltk = _cmac(T, bytes([0x01]) + key_id + n1 + n2 + a1 + a2 + length)

    return mac_key, ltk


def f6(
    w: bytes,
    n1: bytes,
    n2: bytes,
    r: bytes,
    iocap: bytes,
    a1: bytes,
    a2: bytes,
) -> bytes:
    """SC DHKey check (BT Spec Vol 3 Part H §2.2.8).

    f6(W, N1, N2, R, IOcap, A1, A2) = AES-CMAC_W(N1 || N2 || R || IOcap || A1 || A2)
    """
    return _cmac(w, n1 + n2 + r + iocap + a1 + a2)


def g2(u: bytes, v: bytes, x: bytes, y: bytes) -> int:
    """SC numeric comparison (BT Spec Vol 3 Part H §2.2.9).

    g2(U, V, X, Y) = AES-CMAC_X(U || V || Y) — returns full uint32 (bits [31:0]).
    """
    mac = _cmac(x, u + v + y)
    return struct.unpack(">I", mac[12:16])[0]


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate an ephemeral P-256 keypair in BT wire (little-endian) format.

    Returns:
        (private_key, public_key):
        - private_key: 32 bytes, little-endian.
        - public_key:  64 bytes = X (32 bytes LE) || Y (32 bytes LE).
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_value = private_key.private_numbers().private_value
    priv_be = priv_value.to_bytes(32, "big")
    pub_n = private_key.public_key().public_numbers()
    pub_x_be = pub_n.x.to_bytes(32, "big")
    pub_y_be = pub_n.y.to_bytes(32, "big")
    return priv_be[::-1], pub_x_be[::-1] + pub_y_be[::-1]


def dhkey(priv_le: bytes, peer_pub_le: bytes) -> bytes:
    """Compute DHKey = ECDH(priv_le, peer_pub_le).

    Args:
        priv_le:      32-byte little-endian private scalar.
        peer_pub_le:  64-byte little-endian public point (X || Y).

    Returns:
        DHKey: 32-byte little-endian shared X coordinate.
    """
    if len(priv_le) != 32:
        raise ValueError(f"private key must be 32 bytes, got {len(priv_le)}")
    if len(peer_pub_le) != 64:
        raise ValueError(f"public key must be 64 bytes, got {len(peer_pub_le)}")

    priv_be = bytes(reversed(priv_le))
    peer_x_be = bytes(reversed(peer_pub_le[:32]))
    peer_y_be = bytes(reversed(peer_pub_le[32:]))

    priv_value = int.from_bytes(priv_be, "big")
    private_key = ec.derive_private_key(priv_value, ec.SECP256R1())

    peer_x = int.from_bytes(peer_x_be, "big")
    peer_y = int.from_bytes(peer_y_be, "big")
    peer_pub_n = ec.EllipticCurvePublicNumbers(peer_x, peer_y, ec.SECP256R1())
    peer_pub_key = peer_pub_n.public_key()

    shared = private_key.exchange(ec.ECDH(), peer_pub_key)
    return bytes(reversed(shared))
