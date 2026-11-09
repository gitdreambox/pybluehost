"""Encrypted Advertising Data — Core Specification Supplement v15 §1.23.

The "Encrypted Data" AD type (0x31) carries ``Randomizer || Payload || MIC``.
Payload and MIC come from AES-CCM over the plaintext AD structures, with

* the session key and IV taken from the Encrypted Data Key Material
  characteristic (0x2B88, Vol 3 Part C §12.6 — key(16) || IV(8)),
* a 13-octet nonce built from the Randomizer and the IV, both of which are
  carried most-significant-octet first but enter the nonce
  least-significant-octet first (§1.23.3 + the worked example in §2.3.1),
* a single-octet additional authenticated data of 0xEA, and
* a 4-octet MIC.

The CSS publishes two worked examples (§2.3.1/2.3.2) that the tests replay
byte for byte, so the construction here is pinned to the standard rather than
to whatever the current PTS happens to accept.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

EAD_AD_TYPE = 0x31
EAD_AAD = b"\xEA"
EAD_TAG_LENGTH = 4
EAD_RANDOMIZER_LEN = 5
EAD_IV_LEN = 8
EAD_KEY_LEN = 16
# Key Material characteristic value: session key followed by the IV.
EAD_KEY_MATERIAL_LEN = EAD_KEY_LEN + EAD_IV_LEN


@dataclass(frozen=True)
class EADKeyMaterial:
    """The session key + IV pair used to encrypt and authenticate EAD."""

    session_key: bytes
    iv: bytes

    def __post_init__(self) -> None:
        if len(self.session_key) != EAD_KEY_LEN:
            raise ValueError(
                f"EAD session key must be {EAD_KEY_LEN} octets, "
                f"got {len(self.session_key)}"
            )
        if len(self.iv) != EAD_IV_LEN:
            raise ValueError(
                f"EAD IV must be {EAD_IV_LEN} octets, got {len(self.iv)}"
            )

    @classmethod
    def from_characteristic(cls, value: bytes) -> "EADKeyMaterial":
        """Parse the Encrypted Data Key Material characteristic value."""
        if len(value) < EAD_KEY_MATERIAL_LEN:
            raise ValueError(
                "Encrypted Data Key Material must be at least "
                f"{EAD_KEY_MATERIAL_LEN} octets, got {len(value)}"
            )
        return cls(session_key=bytes(value[:EAD_KEY_LEN]),
                   iv=bytes(value[EAD_KEY_LEN:EAD_KEY_MATERIAL_LEN]))


def _nonce(randomizer_wire: bytes, iv: bytes) -> bytes:
    """CCM nonce: the Randomizer as carried, then the IV reversed.

    The CSS worked example settles both orders: the Encrypted Data AD payload
    starts ``18 E1 57 CA DE`` for randomizer 0xDECA57E118 (quoted MSO first),
    and that same five-octet run is the head of ``a0``/``b0`` — so the
    Randomizer enters the nonce exactly as it appears on the wire. The IV does
    get reversed (0x46E77AB1EF007A9E becomes 9E 7A 00 EF B1 7A E7 46).
    """
    return randomizer_wire + iv[::-1]


def encrypt_ead(
    plaintext: bytes,
    material: EADKeyMaterial,
    *,
    randomizer: bytes | None = None,
) -> bytes:
    """Return the Encrypted Data AD payload: ``Randomizer || ciphertext || MIC``.

    ``randomizer`` is the 5-octet field in *wire* (least-significant-octet
    first) order; a fresh random one is generated when not supplied.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    if randomizer is None:
        randomizer = os.urandom(EAD_RANDOMIZER_LEN)
    if len(randomizer) != EAD_RANDOMIZER_LEN:
        raise ValueError(
            f"EAD randomizer must be {EAD_RANDOMIZER_LEN} octets, "
            f"got {len(randomizer)}"
        )
    ciphertext_and_mic = AESCCM(
        material.session_key, tag_length=EAD_TAG_LENGTH,
    ).encrypt(_nonce(randomizer, material.iv), plaintext, EAD_AAD)
    return bytes(randomizer) + ciphertext_and_mic


def decrypt_ead(ead: bytes, material: EADKeyMaterial) -> bytes:
    """Recover the plaintext AD structures from an Encrypted Data payload.

    Raises ``InvalidTag`` when the MIC does not verify.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    if len(ead) < EAD_RANDOMIZER_LEN + EAD_TAG_LENGTH:
        raise ValueError(f"EAD payload too short: {len(ead)} octets")
    randomizer = bytes(ead[:EAD_RANDOMIZER_LEN])
    body = bytes(ead[EAD_RANDOMIZER_LEN:])
    return AESCCM(
        material.session_key, tag_length=EAD_TAG_LENGTH,
    ).decrypt(_nonce(randomizer, material.iv), body, EAD_AAD)
