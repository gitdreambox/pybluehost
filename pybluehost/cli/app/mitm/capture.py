"""抓包 tap:把被中继的 L2CAP PDU 写进 btsnoop(v1 只观测,不改写)。

复用 core.trace.BtsnoopSink(纯 btsnoop 文件写入器,非协议逻辑)。
未来改写阶段在此 tap 点替换为 InterceptionPipeline。

性能:磁盘写入(BtsnoopSink 每包 write+flush)放在后台 drain 任务里,
``on_pdu`` 只做入队(同步、瞬时),**绝不阻塞转发热路径**。AclRelay 也已
改为"先转发、后抓包",抓包延迟因此完全不计入 phone↔target 的转发 RTT。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

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
    """把每条中继 PDU 重新包成 HCI ACL 记录写入 btsnoop(后台异步,不阻塞转发)。"""

    def __init__(self, path: str | Path) -> None:
        self._sink = BtsnoopSink(path)
        # 后台写盘:on_pdu 入队即返回,_drain 任务串行写入(保序),磁盘 flush 不挡转发。
        self._queue: asyncio.Queue[Optional[TraceEvent]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closed = False

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        if self._closed:
            return
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
        # 首次写入时惰性启动后台 drain(此处必在 relay 的运行 loop 内)。
        if self._task is None:
            self._task = asyncio.ensure_future(self._drain())
        self._queue.put_nowait(event)

    async def _drain(self) -> None:
        """串行写入队列中的事件(保序);收到 None 哨兵退出。"""
        while True:
            event = await self._queue.get()
            if event is None:
                return
            try:
                await self._sink.on_trace(event)
            except Exception:
                # 抓包失败不应影响中继(已在转发之后);吞掉并继续。
                pass

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            # 入哨兵让 drain 写完所有已入队事件再退出,确保 close 返回时已全部落盘。
            self._queue.put_nowait(None)
            await self._task
            self._task = None
        await self._sink.close()
