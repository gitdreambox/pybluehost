"""HCI controller capability inspection.

SupportedCommands wraps the 64-byte bitmap returned by HCI_Read_Local_Supported_Commands
(Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 "Supported_Commands"). The bitmap
encodes "this controller implements command X" as a single bit at a (octet, bit)
coordinate documented in the table. ``has(opcode)`` returns True iff the bit for
the given opcode is set; unknown opcodes return False.
"""
from __future__ import annotations

from dataclasses import dataclass

from pybluehost.hci.constants import (
    HCI_HOST_BUFFER_SIZE,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)


# Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 — Supported_Commands bitmap layout.
# Maps each opcode that HCIController.initialize() issues to its (octet, bit) position.
# If you add a new command to initialize(), add its entry here too.
_OPCODE_BIT_POSITIONS: dict[int, tuple[int, int]] = {
    HCI_RESET:                              (5, 7),
    HCI_SET_EVENT_MASK:                     (5, 6),
    HCI_WRITE_SCAN_ENABLE:                  (6, 2),
    HCI_HOST_BUFFER_SIZE:                   (10, 6),
    HCI_READ_LOCAL_VERSION:                 (14, 3),
    HCI_READ_LOCAL_SUPPORTED_FEATURES:      (14, 4),
    HCI_READ_LOCAL_SUPPORTED_COMMANDS:      (14, 5),
    HCI_READ_BUFFER_SIZE:                   (14, 7),
    HCI_READ_BD_ADDR:                       (15, 1),
    HCI_WRITE_SIMPLE_PAIRING_MODE:          (17, 6),
    HCI_WRITE_LE_HOST_SUPPORTED:            (24, 6),
    HCI_LE_SET_EVENT_MASK:                  (25, 0),
    HCI_LE_SET_RANDOM_ADDRESS:              (25, 4),
    HCI_LE_READ_BUFFER_SIZE:                (25, 7),
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES:   (26, 0),
    HCI_LE_SET_SCAN_PARAMS:                 (26, 2),
}


@dataclass(frozen=True)
class SupportedCommands:
    """64-byte HCI Supported_Commands bitmap with opcode lookup."""

    bitmap: bytes

    def __post_init__(self) -> None:
        if len(self.bitmap) != 64:
            raise ValueError(
                f"SupportedCommands bitmap must be 64 bytes, got {len(self.bitmap)}"
            )

    def has(self, opcode: int) -> bool:
        """Return True iff the controller advertises support for the given opcode.

        Unknown opcodes return False.
        """
        position = _OPCODE_BIT_POSITIONS.get(opcode)
        if position is None:
            return False
        octet, bit = position
        return bool(self.bitmap[octet] & (1 << bit))
