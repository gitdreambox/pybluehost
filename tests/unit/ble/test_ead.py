"""Encrypted Advertising Data — replayed against the CSS v15 worked examples.

CSS v15 §2.3 publishes two complete sample sets (inputs, every intermediate
block and the encrypted output), so these tests pin the construction to the
standard rather than to whatever the current PTS accepts.
"""
from __future__ import annotations

import pytest

from pybluehost.ble.ead import (
    EADKeyMaterial,
    decrypt_ead,
    encrypt_ead,
)

# CSS v15 §2.3.1/2.3.2 share the plaintext, key and IV; only the randomizer
# differs.
_PLAINTEXT = bytes.fromhex("0F0953686F7274204D696E692D42757303190A8C")
_KEY = bytes.fromhex("57A9DA12D12E6E131E20612AD10A6A19")
_IV = bytes.fromhex("46E77AB1EF007A9E")

_SETS = [
    # (randomizer MSO->LSO, expected Encrypted Data AD payload)
    ("DECA57E118",
     "18E157CADE74E4DCAFDC51C7282810C2217F0E4CEF4343181FBA0069CC"),
    ("7A6E971C8D",
     "8D1C976E7A35444076125788C238A58E8BD9CFF0DEFE251A8E7275454C"),
]


@pytest.mark.parametrize("randomizer,expected", _SETS)
def test_encrypt_ead_matches_the_css_sample_data(randomizer, expected):
    material = EADKeyMaterial(session_key=_KEY, iv=_IV)
    # The CSS quotes the randomizer most-significant-octet first; on the wire
    # (and in the AD data) it is least-significant-octet first.
    wire_randomizer = bytes.fromhex(randomizer)[::-1]

    assert encrypt_ead(_PLAINTEXT, material,
                       randomizer=wire_randomizer).hex().upper() == expected


@pytest.mark.parametrize("randomizer,expected", _SETS)
def test_decrypt_ead_round_trips_the_css_sample_data(randomizer, expected):
    material = EADKeyMaterial(session_key=_KEY, iv=_IV)

    assert decrypt_ead(bytes.fromhex(expected), material) == _PLAINTEXT


def test_decrypt_ead_rejects_a_tampered_payload():
    from cryptography.exceptions import InvalidTag

    material = EADKeyMaterial(session_key=_KEY, iv=_IV)
    tampered = bytearray(bytes.fromhex(_SETS[0][1]))
    tampered[8] ^= 0x01

    with pytest.raises(InvalidTag):
        decrypt_ead(bytes(tampered), material)


def test_key_material_from_characteristic_splits_key_and_iv():
    value = _KEY + _IV
    material = EADKeyMaterial.from_characteristic(value)

    assert material.session_key == _KEY
    assert material.iv == _IV


def test_key_material_rejects_short_values():
    with pytest.raises(ValueError, match="at least"):
        EADKeyMaterial.from_characteristic(_KEY)


def test_key_material_validates_field_lengths():
    with pytest.raises(ValueError, match="session key"):
        EADKeyMaterial(session_key=_KEY[:-1], iv=_IV)
    with pytest.raises(ValueError, match="IV"):
        EADKeyMaterial(session_key=_KEY, iv=_IV[:-1])


def test_encrypt_ead_generates_a_randomizer_when_omitted():
    material = EADKeyMaterial(session_key=_KEY, iv=_IV)
    first = encrypt_ead(_PLAINTEXT, material)
    second = encrypt_ead(_PLAINTEXT, material)

    assert len(first) == 5 + len(_PLAINTEXT) + 4
    assert first[:5] != second[:5]
    assert decrypt_ead(first, material) == _PLAINTEXT
