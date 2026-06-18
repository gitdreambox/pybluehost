"""AVRCP v1.6 — Audio/Video Remote Control Profile.

Rides AVCTP (pybluehost.avctp). PSM 0x0017. Two roles:
- AVRCPController — issues PASS_THROUGH commands, subscribes to notifications.
- AVRCPTarget — accepts commands, emits notifications.
"""
from pybluehost.classic.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
    AVRCPEventID, AVRCPMetadataPDU, AVRCPOperationID, AVRCPPlayStatus,
    AVRCP_BT_SIG_COMPANY_ID,
)
from pybluehost.classic.avrcp.frame import AVCFrame

__all__ = [
    "AVCFrame", "AVCCtype", "AVCOpCode", "AVCSubunitType",
    "AVRCPEventID", "AVRCPMetadataPDU", "AVRCPOperationID", "AVRCPPlayStatus",
    "AVRCP_BT_SIG_COMPANY_ID",
]
