"""Unit tests for _OPCODE_BIT_POSITIONS coverage of BR/EDR + SSP + LE SC opcodes."""
from __future__ import annotations

from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
from pybluehost.hci.constants import (
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_INQUIRY,
    HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_LE_GENERATE_DHKEY,
    HCI_LE_READ_LOCAL_P256_PUBLIC_KEY,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_WRITE_SCAN_ENABLE,
)


def test_bredr_basic_opcodes_in_map():
    for opcode in (HCI_INQUIRY, HCI_CREATE_CONNECTION, HCI_DISCONNECT):
        assert opcode in _OPCODE_BIT_POSITIONS, (
            f"opcode 0x{opcode:04X} missing from _OPCODE_BIT_POSITIONS"
        )


def test_bredr_ssp_opcodes_in_map():
    for opcode in (
        HCI_AUTH_REQUESTED,
        HCI_IO_CAPABILITY_REQUEST_REPLY,
        HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY,
        HCI_USER_CONFIRMATION_REQUEST_REPLY,
        HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
        HCI_SET_CONNECTION_ENCRYPTION,
        HCI_LINK_KEY_REQUEST_REPLY,
    ):
        assert opcode in _OPCODE_BIT_POSITIONS


def test_le_sc_opcodes_in_map():
    assert HCI_LE_READ_LOCAL_P256_PUBLIC_KEY in _OPCODE_BIT_POSITIONS
    assert HCI_LE_GENERATE_DHKEY in _OPCODE_BIT_POSITIONS


def test_le_sc_opcode_positions_match_octet_34():
    """LE SC capability gate uses octet 34 — see tests/e2e/_helpers.py:25."""
    assert _OPCODE_BIT_POSITIONS[HCI_LE_READ_LOCAL_P256_PUBLIC_KEY] == (34, 1)
    assert _OPCODE_BIT_POSITIONS[HCI_LE_GENERATE_DHKEY] == (34, 2)


def test_ssp_opcode_positions_match_spec():
    """SSP reply commands live at octets 18-20 per Spec 5.4 Table 6.27.
    Real-hardware survey 2026-05 verified BT 4.0 adapters (CSR8510) have
    these bits set even when BT 4.1 commands at octet 32 are missing."""
    from pybluehost.hci.constants import (
        HCI_IO_CAPABILITY_REQUEST_REPLY,
        HCI_USER_CONFIRMATION_REQUEST_REPLY,
        HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
        HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY,
    )
    assert _OPCODE_BIT_POSITIONS[HCI_IO_CAPABILITY_REQUEST_REPLY] == (18, 7)
    assert _OPCODE_BIT_POSITIONS[HCI_USER_CONFIRMATION_REQUEST_REPLY] == (19, 0)
    assert _OPCODE_BIT_POSITIONS[HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY] == (19, 1)
    assert _OPCODE_BIT_POSITIONS[HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY] == (20, 3)


def test_write_scan_enable_still_in_map():
    assert HCI_WRITE_SCAN_ENABLE in _OPCODE_BIT_POSITIONS


def test_all_values_are_octet_bit_tuples():
    for opcode, position in _OPCODE_BIT_POSITIONS.items():
        assert isinstance(position, tuple) and len(position) == 2
        octet, bit = position
        assert 0 <= octet <= 63, f"opcode 0x{opcode:04X} octet={octet} out of range"
        assert 0 <= bit <= 7, f"opcode 0x{opcode:04X} bit={bit} out of range"
