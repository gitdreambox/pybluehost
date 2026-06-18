"""AVCTP v1.4 constants — packet types, direction bits, AVRCP profile UUIDs.

AVCTP runs on Classic L2CAP PSM 0x0017 (signaling) and 0x001B (browsing,
not in scope for A.3). Single channel per peer; transaction tracking is
session-layer.
"""
from __future__ import annotations

from enum import IntEnum


PSM_AVCTP = 0x0017        # AVCTP signaling channel
PSM_AVCTP_BROWSING = 0x001B   # browsing channel — out of scope for A.3


class AVCTPPacketType(IntEnum):
    """AVCTP v1.4 §6.1 — 2-bit fragmentation packet type."""
    SINGLE = 0
    START = 1
    CONTINUE = 2
    END = 3


class AVCTPMessageDirection(IntEnum):
    """AVCTP v1.4 §6.1.1 — C/R bit."""
    COMMAND = 0
    RESPONSE = 1


# AVRCP v1.6 §6 — Bluetooth-assigned UUIDs.
AVRCP_PROFILE_UUID = 0x110E      # "AVRemoteControl" (legacy / generic)
AVRCP_CONTROLLER_UUID = 0x110F   # "AVRemoteControlController"
AVRCP_TARGET_UUID = 0x110C       # "AVRemoteControlTarget"
