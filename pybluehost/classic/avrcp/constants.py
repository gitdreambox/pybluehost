"""AVRCP v1.6 and AV/C v4.0 constants."""
from __future__ import annotations

from enum import IntEnum


class AVCCtype(IntEnum):
    """AV/C v4.0 §7.3.1 — Command/Response type (4 bits)."""
    CONTROL = 0x0
    STATUS = 0x1
    SPECIFIC_INQUIRY = 0x2
    NOTIFY = 0x3
    GENERAL_INQUIRY = 0x4
    NOT_IMPLEMENTED = 0x8
    ACCEPTED = 0x9
    REJECTED = 0xA
    IN_TRANSITION = 0xB
    STABLE = 0xC   # also IMPLEMENTED in some contexts
    CHANGED = 0xD
    INTERIM = 0xF


class AVCSubunitType(IntEnum):
    """AV/C v4.0 §7.3.2 — Subunit type (5 bits). AVRCP uses PANEL almost exclusively."""
    MONITOR = 0x00
    AUDIO = 0x01
    PRINTER = 0x02
    DISC_RECORDER = 0x03
    TAPE_RECORDER = 0x04
    TUNER = 0x05
    CA = 0x06
    CAMERA = 0x07
    PANEL = 0x09
    BULLETIN_BOARD = 0x0A
    CAMERA_STORAGE = 0x0B
    MUSIC = 0x0C
    UNIT = 0x1F


class AVCOpCode(IntEnum):
    """AV/C v4.0 + AVRCP v1.6 — Operation codes used in AVRCP."""
    VENDOR_DEPENDENT = 0x00
    UNIT_INFO = 0x30
    SUBUNIT_INFO = 0x31
    PASS_THROUGH = 0x7C


class AVRCPOperationID(IntEnum):
    """AVRCP v1.6 §4.6 — PASS_THROUGH operation IDs (7 bits)."""
    SELECT = 0x00
    UP = 0x01
    DOWN = 0x02
    LEFT = 0x03
    RIGHT = 0x04
    ENTER = 0x09
    PLAY = 0x44
    STOP = 0x45
    PAUSE = 0x46
    RECORD = 0x47
    REWIND = 0x48
    FAST_FORWARD = 0x49
    EJECT = 0x4A
    FORWARD = 0x4B    # Next
    BACKWARD = 0x4C   # Prev
    VOLUME_UP = 0x41
    VOLUME_DOWN = 0x42
    MUTE = 0x43


class AVRCPEventID(IntEnum):
    """AVRCP v1.6 §6.7 — Notification event identifiers."""
    PLAYBACK_STATUS_CHANGED = 0x01
    TRACK_CHANGED = 0x02
    TRACK_REACHED_END = 0x03
    TRACK_REACHED_START = 0x04
    PLAYBACK_POS_CHANGED = 0x05
    BATT_STATUS_CHANGED = 0x06
    SYSTEM_STATUS_CHANGED = 0x07
    PLAYER_APPLICATION_SETTING_CHANGED = 0x08
    NOW_PLAYING_CONTENT_CHANGED = 0x09
    AVAILABLE_PLAYERS_CHANGED = 0x0A
    ADDRESSED_PLAYER_CHANGED = 0x0B
    UIDS_CHANGED = 0x0C
    VOLUME_CHANGED = 0x0D


class AVRCPPlayStatus(IntEnum):
    """AVRCP v1.6 §6.7.1 — EVENT_PLAYBACK_STATUS_CHANGED play status values."""
    STOPPED = 0x00
    PLAYING = 0x01
    PAUSED = 0x02
    FWD_SEEK = 0x03
    REV_SEEK = 0x04
    ERROR = 0xFF


# Vendor-dependent PDU — AVRCP v1.6 Bluetooth SIG company ID + metadata PDU IDs.
AVRCP_BT_SIG_COMPANY_ID = 0x001958


class AVRCPMetadataPDU(IntEnum):
    """AVRCP v1.6 §6.5 — metadata transfer PDU IDs (over VENDOR_DEPENDENT opcode)."""
    GET_CAPABILITIES = 0x10
    GET_PLAY_STATUS = 0x30
    REGISTER_NOTIFICATION = 0x31
    REQUEST_CONTINUING_RESPONSE = 0x40
    ABORT_CONTINUING_RESPONSE = 0x41
    SET_ABSOLUTE_VOLUME = 0x50
