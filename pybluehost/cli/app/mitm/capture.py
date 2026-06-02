"""抓包 tap:把被中继的 L2CAP PDU 写进 btsnoop(v1 只观测,不改写)。

复用 core.trace.BtsnoopSink(纯 btsnoop 文件写入器,非协议逻辑)。
未来改写阶段在此 tap 点替换为 InterceptionPipeline。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pybluehost.cli.app.mitm.acl import PB_FIRST_FLUSH, RelayDirection
from pybluehost.core.trace import BtsnoopSink, Direction, TraceEvent
from pybluehost.hci.packets import HCIACLData


class CaptureTap(Protocol):
    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None: ...
    async def close(self) -> None: ...


class NullTap:
    """不抓包。"""

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        return None

    async def close(self) -> None:
        return None


class BtsnoopCaptureTap:
    """把每条中继 PDU 重新包成 HCI ACL 记录写入 btsnoop。"""

    def __init__(self, path: str | Path) -> None:
        self._sink = BtsnoopSink(path)

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        # l2cap_pdu 是完整 L2CAP 帧(含 2 字节 length + 2 字节 CID 的 basic header),
        # 即 AclRelay 里 encode_l2cap_basic() 的输出 —— 直接作为 ACL payload 落盘,
        # Wireshark/Ellisys 才能正确解析。
        acl = HCIACLData(handle=handle, pb_flag=PB_FIRST_FLUSH, data=l2cap_pdu)
        now = datetime.now(timezone.utc)
        bt_dir = (
            Direction.UP
            if direction is RelayDirection.TARGET_TO_PHONE
            else Direction.DOWN
        )
        event = TraceEvent(
            timestamp=now.timestamp(),
            wall_clock=now,
            source_layer="hci",  # 必须 ∈ BtsnoopSink._HCI_LAYERS,否则记录被静默丢弃

            direction=bt_dir,
            raw_bytes=acl.to_bytes(),
            decoded=None,
            connection_handle=handle,
            metadata={"mitm_direction": direction.value},
        )
        await self._sink.on_trace(event)

    async def close(self) -> None:
        await self._sink.close()
