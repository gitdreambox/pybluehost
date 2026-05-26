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
    HCI_ACCEPT_CONNECTION_REQ,
    HCI_AUTH_REQUESTED,
    HCI_CREATE_CONNECTION,
    HCI_DISCONNECT,
    HCI_HOST_BUFFER_SIZE,
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_LE_GENERATE_DHKEY,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_P256_PUBLIC_KEY,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY,
    HCI_PIN_CODE_REQUEST_REPLY,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_EXTENDED_FEATURES,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_REJECT_CONNECTION_REQ,
    HCI_RESET,
    HCI_SET_CONNECTION_ENCRYPTION,
    HCI_SET_EVENT_MASK,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)


# Core Spec 5.4 Vol 4 Part E §6.27, Table 6.27 — Supported_Commands bitmap layout.
# Maps each opcode that HCIController.initialize() issues to its (octet, bit) position.
# If you add a new command to initialize(), add its entry here too.
_OPCODE_BIT_POSITIONS: dict[int, tuple[int, int]] = {
    # BR/EDR Link Control (Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27)
    HCI_INQUIRY:                                  (0, 0),
    HCI_INQUIRY_CANCEL:                           (0, 1),
    HCI_CREATE_CONNECTION:                        (0, 4),
    HCI_DISCONNECT:                               (0, 5),
    HCI_ACCEPT_CONNECTION_REQ:                    (1, 0),
    HCI_REJECT_CONNECTION_REQ:                    (1, 1),
    HCI_LINK_KEY_REQUEST_REPLY:                   (1, 2),
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY:          (1, 3),
    HCI_PIN_CODE_REQUEST_REPLY:                   (1, 4),
    HCI_PIN_CODE_REQUEST_NEGATIVE_REPLY:          (1, 5),
    HCI_AUTH_REQUESTED:                           (1, 7),
    HCI_SET_CONNECTION_ENCRYPTION:                (2, 1),
    # Controller & Baseband
    HCI_SET_EVENT_MASK:                           (5, 6),
    HCI_RESET:                                    (5, 7),
    HCI_WRITE_SCAN_ENABLE:                        (6, 2),
    HCI_HOST_BUFFER_SIZE:                         (10, 6),
    HCI_READ_LOCAL_VERSION:                       (14, 3),
    HCI_READ_LOCAL_SUPPORTED_FEATURES:            (14, 4),
    HCI_READ_LOCAL_SUPPORTED_COMMANDS:            (14, 5),
    HCI_READ_LOCAL_EXTENDED_FEATURES:             (14, 6),
    HCI_READ_BUFFER_SIZE:                         (14, 7),
    HCI_READ_BD_ADDR:                             (15, 1),
    HCI_WRITE_SIMPLE_PAIRING_MODE:                (17, 6),
    HCI_WRITE_LE_HOST_SUPPORTED:                  (24, 6),
    # LE
    HCI_LE_SET_EVENT_MASK:                        (25, 0),
    HCI_LE_SET_RANDOM_ADDRESS:                    (25, 4),
    HCI_LE_READ_BUFFER_SIZE:                      (25, 7),
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES:         (26, 0),
    HCI_LE_SET_SCAN_PARAMS:                       (26, 2),
    # SSP commands at octet 32-33
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT:    (32, 3),
    HCI_IO_CAPABILITY_REQUEST_REPLY:              (32, 5),
    HCI_USER_CONFIRMATION_REQUEST_REPLY:          (32, 6),
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY: (32, 7),
    HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY:     (33, 5),
    # LE Secure Connections (verified by tests/e2e/_helpers.py:25-27)
    HCI_LE_READ_LOCAL_P256_PUBLIC_KEY:            (34, 1),
    HCI_LE_GENERATE_DHKEY:                        (34, 2),
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
