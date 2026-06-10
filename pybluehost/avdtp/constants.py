"""AVDTP v1.3 constants — signal IDs, packet types, error codes, service categories."""
from __future__ import annotations

from enum import IntEnum


PSM_AVDTP = 0x0019   # A2DP signaling + media share this PSM (separate channels)


class AVDTPSignalID(IntEnum):
    """AVDTP v1.3 §8.5 — 6-bit signal identifier."""
    DISCOVER = 0x01
    GET_CAPABILITIES = 0x02
    SET_CONFIGURATION = 0x03
    GET_CONFIGURATION = 0x04
    RECONFIGURE = 0x05
    OPEN = 0x06
    START = 0x07
    CLOSE = 0x08
    SUSPEND = 0x09
    ABORT = 0x0A
    SECURITY_CONTROL = 0x0B
    GET_ALL_CAPABILITIES = 0x0C
    DELAYREPORT = 0x0D


class AVDTPPacketType(IntEnum):
    """AVDTP v1.3 §8.4.1 — message-fragmentation packet type."""
    SINGLE = 0
    START = 1
    CONTINUE = 2
    END = 3


class AVDTPMessageType(IntEnum):
    """AVDTP v1.3 §8.4.2 — message direction/result."""
    COMMAND = 0
    GENERAL_REJECT = 1
    RESPONSE_ACCEPT = 2
    RESPONSE_REJECT = 3


class AVDTPErrorCode(IntEnum):
    """AVDTP v1.3 §8.20 — signaling error codes."""
    BAD_HEADER_FORMAT = 0x01
    BAD_LENGTH = 0x11
    BAD_ACP_SEID = 0x12
    SEP_IN_USE = 0x13
    SEP_NOT_IN_USE = 0x14
    BAD_SERV_CATEGORY = 0x17
    BAD_PAYLOAD_FORMAT = 0x18
    NOT_SUPPORTED_COMMAND = 0x19
    INVALID_CAPABILITIES = 0x1A
    BAD_RECOVERY_TYPE = 0x22
    BAD_MEDIA_TRANSPORT_FORMAT = 0x23
    BAD_RECOVERY_FORMAT = 0x25
    BAD_ROHC_FORMAT = 0x26
    BAD_CP_FORMAT = 0x27
    BAD_MULTIPLEXING_FORMAT = 0x28
    UNSUPPORTED_CONFIGURATION = 0x29
    BAD_STATE = 0x31


class MediaType(IntEnum):
    AUDIO = 0x00
    VIDEO = 0x01
    MULTIMEDIA = 0x02


class TSEP(IntEnum):
    """Stream End-Point type (Source or Sink)."""
    SRC = 0
    SNK = 1


class ServiceCategory(IntEnum):
    """AVDTP v1.3 §8.21 — capability/configuration service categories."""
    MEDIA_TRANSPORT = 0x01
    REPORTING = 0x02
    RECOVERY = 0x03
    CONTENT_PROTECTION = 0x04
    HEADER_COMPRESSION = 0x05
    MULTIPLEXING = 0x06
    MEDIA_CODEC = 0x07
    DELAY_REPORTING = 0x08


# A2DP v1.4 §4.3.2 — SBC codec type within MEDIA_CODEC capability
A2DP_CODEC_TYPE_SBC = 0x00
A2DP_CODEC_TYPE_MPEG12 = 0x01
A2DP_CODEC_TYPE_MPEG24_AAC = 0x02
A2DP_CODEC_TYPE_ATRAC = 0x04
A2DP_CODEC_TYPE_NON_A2DP = 0xFF
