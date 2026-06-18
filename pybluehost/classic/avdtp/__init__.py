"""AVDTP — Audio/Video Distribution Transport Protocol (v1.3).

PSM 0x0019. Two channels per session: signaling (commands/responses) and
media (audio packets, RTP-style framing). Used by A2DP and VDP profiles.
"""
from pybluehost.classic.avdtp.constants import (
    AVDTPSignalID, AVDTPPacketType, AVDTPMessageType, AVDTPErrorCode,
    MediaType, TSEP, ServiceCategory, PSM_AVDTP,
    A2DP_CODEC_TYPE_SBC, A2DP_CODEC_TYPE_MPEG12, A2DP_CODEC_TYPE_MPEG24_AAC,
    A2DP_CODEC_TYPE_ATRAC, A2DP_CODEC_TYPE_NON_A2DP,
)

__all__ = [
    "AVDTPSignalID", "AVDTPPacketType", "AVDTPMessageType", "AVDTPErrorCode",
    "MediaType", "TSEP", "ServiceCategory", "PSM_AVDTP",
    "A2DP_CODEC_TYPE_SBC", "A2DP_CODEC_TYPE_MPEG12", "A2DP_CODEC_TYPE_MPEG24_AAC",
    "A2DP_CODEC_TYPE_ATRAC", "A2DP_CODEC_TYPE_NON_A2DP",
]
