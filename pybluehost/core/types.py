from __future__ import annotations

from enum import IntEnum


class IOCapability(IntEnum):
    DISPLAY_ONLY = 0x00
    DISPLAY_YES_NO = 0x01
    KEYBOARD_ONLY = 0x02
    NO_INPUT_NO_OUTPUT = 0x03
    KEYBOARD_DISPLAY = 0x04


class ConnectionRole(IntEnum):
    CENTRAL = 0x00
    PERIPHERAL = 0x01


class LinkType(IntEnum):
    SCO = 0x00
    ACL = 0x01
    ESCO = 0x02
    LE = 0x03
