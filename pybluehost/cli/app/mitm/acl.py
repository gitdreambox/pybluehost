"""HCI ACL 透传核心:L2CAP PDU 重组、CID 分流、跨 buffer 重分片。

本模块只认 HCI 分片边界 + L2CAP basic header(2 字节 length + 2 字节 CID),
与 BLE/BR 无关,故两种 transport 共用。
"""
from __future__ import annotations

import struct
from enum import Enum, auto

from pybluehost.hci.packets import HCIACLData

# HCI ACL Packet Boundary flags (Core Vol4 Part E §5.4.2)
PB_FIRST_NON_FLUSH = 0x00  # host→controller 首片(非自动 flush)
PB_CONTINUATION = 0x01     # 续片
PB_FIRST_FLUSH = 0x02      # 首片(自动 flush;接收方向常见)

# 固定 CID
CID_BR_SIGNALING = 0x0001
CID_ATT = 0x0004
CID_LE_SIGNALING = 0x0005
CID_SMP = 0x0006


class RelayDirection(Enum):
    PHONE_TO_TARGET = "phone→target"
    TARGET_TO_PHONE = "target→phone"


class CidAction(Enum):
    RELAY = auto()          # 透明转发(ATT/动态/signaling)
    TERMINATE_SMP = auto()  # 本地终结(BLE SMP, MITM-2 接管)


def classify(cid: int) -> CidAction:
    """决定一个 L2CAP CID 是本地终结还是透明转发。"""
    if cid == CID_SMP:
        return CidAction.TERMINATE_SMP
    return CidAction.RELAY


def encode_l2cap_basic(cid: int, payload: bytes) -> bytes:
    """把 (cid, payload) 编成 L2CAP basic header 帧。"""
    return struct.pack("<HH", len(payload), cid) + payload
