"""SupportedCommands parses the 64-byte HCI Read_Local_Supported_Commands bitmap."""
from __future__ import annotations

import pytest

from pybluehost.hci.capabilities import SupportedCommands
from pybluehost.hci.constants import (
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_READ_BD_ADDR,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
)


def test_supported_commands_requires_64_byte_bitmap():
    """Construction rejects bitmaps that aren't exactly 64 bytes."""
    with pytest.raises(ValueError):
        SupportedCommands(bytes(63))
    with pytest.raises(ValueError):
        SupportedCommands(bytes(65))


def test_all_ones_bitmap_supports_every_known_opcode():
    caps = SupportedCommands(b"\xFF" * 64)
    assert caps.has(HCI_RESET)
    assert caps.has(HCI_READ_BD_ADDR)
    assert caps.has(HCI_LE_READ_BUFFER_SIZE)
    assert caps.has(HCI_LE_SET_RANDOM_ADDRESS)
    assert caps.has(HCI_LE_SET_SCAN_PARAMS)
    assert caps.has(HCI_SET_EVENT_MASK)
    assert caps.has(HCI_READ_LOCAL_SUPPORTED_COMMANDS)


def test_all_zeros_bitmap_supports_nothing_known():
    caps = SupportedCommands(b"\x00" * 64)
    assert not caps.has(HCI_RESET)
    assert not caps.has(HCI_READ_BD_ADDR)
    assert not caps.has(HCI_LE_READ_BUFFER_SIZE)


def test_opcode_outside_registry_returns_false():
    """Unknown opcodes (not in our gating table) report as unsupported."""
    caps = SupportedCommands(b"\xFF" * 64)
    assert caps.has(0xFFFF) is False


def test_hci_reset_bit_is_octet5_bit7():
    """HCI_Reset is at octet 5 bit 7 (Spec 6.1 §6.27 Table 6.27).

    Octet 5 layout per spec: bit 5=Flow_Specification, bit 6=Set_Event_Mask,
    bit 7=Reset.
    """
    bitmap = bytearray(64)
    bitmap[5] = 0b1000_0000
    caps = SupportedCommands(bytes(bitmap))
    assert caps.has(HCI_RESET)

    bitmap[5] = 0b0111_1111
    caps = SupportedCommands(bytes(bitmap))
    assert not caps.has(HCI_RESET)


def test_read_bd_addr_bit_is_octet15_bit1():
    """Read_BD_ADDR is at octet 15 bit 1 (Core 5.4 Vol 4 Part E Table 6.27)."""
    bitmap = bytearray(64)
    bitmap[15] = 0b0000_0010
    caps = SupportedCommands(bytes(bitmap))
    assert caps.has(HCI_READ_BD_ADDR)

    bitmap[15] = 0b1111_1101
    caps = SupportedCommands(bytes(bitmap))
    assert not caps.has(HCI_READ_BD_ADDR)
