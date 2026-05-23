"""Unit tests for HCI feature-bitmap decoding tables."""
from __future__ import annotations

from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    HCI_VERSION_NAMES,
    LE_FEATURE_BIT_NAMES,
    MANUFACTURER_NAMES,
    hci_version_name,
    manufacturer_name,
)


def test_le_feature_bit_names_has_le_encryption():
    assert LE_FEATURE_BIT_NAMES[(0, 0)] == "LE Encryption"


def test_le_feature_bit_names_has_le_2m_phy():
    assert LE_FEATURE_BIT_NAMES[(1, 0)] == "LE 2M PHY"


def test_le_feature_bit_names_keys_are_octet_bit_tuples():
    for key in LE_FEATURE_BIT_NAMES:
        assert isinstance(key, tuple) and len(key) == 2
        octet, bit = key
        assert 0 <= octet <= 7
        assert 0 <= bit <= 7


def test_bredr_feature_bit_names_has_encryption():
    # BR/EDR Features page 0 byte 0 bit 2 is "Encryption"
    assert BREDR_FEATURE_BIT_NAMES[(0, 2)] == "Encryption"


def test_bredr_feature_bit_names_keys_are_octet_bit_tuples():
    for key in BREDR_FEATURE_BIT_NAMES:
        assert isinstance(key, tuple) and len(key) == 2


def test_manufacturer_names_intel():
    assert MANUFACTURER_NAMES[0x0002] == "Intel Corp."


def test_manufacturer_names_realtek():
    assert MANUFACTURER_NAMES[0x005D] == "Realtek Semiconductor Corp."


def test_manufacturer_name_unknown_id_returns_fallback():
    name = manufacturer_name(0xDEAD)
    assert "Unknown" in name and "DEAD" in name.upper()


def test_manufacturer_name_known_id_returns_name():
    assert manufacturer_name(0x0002) == "Intel Corp."


def test_hci_version_names_cover_4_0_through_5_4():
    assert HCI_VERSION_NAMES[0x06] == "Bluetooth 4.0"
    assert HCI_VERSION_NAMES[0x08] == "Bluetooth 4.2"
    assert HCI_VERSION_NAMES[0x09] == "Bluetooth 5.0"
    assert HCI_VERSION_NAMES[0x0D] == "Bluetooth 5.4"


def test_hci_version_name_known_returns_name():
    assert hci_version_name(0x0D) == "Bluetooth 5.4"


def test_hci_version_name_unknown_returns_fallback():
    name = hci_version_name(0xFF)
    assert "Unknown" in name and "FF" in name.upper()
