"""从两个 transport 字符串构造并初始化上下游 HCIController(仅 hci+transport)。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.hci.controller import HCIController
from pybluehost.transport.base import Transport

logger = logging.getLogger(__name__)


async def _close_transport(t: object) -> None:
    """关闭一个 transport,兼容同步/异步 close;吞掉异常并告警。"""
    close = getattr(t, "close", None)
    if close is None:
        return
    try:
        res = close()
        if asyncio.iscoroutine(res):
            await res
    except Exception:  # 关闭失败不应阻断其它 transport 的清理
        logger.warning("关闭 transport %r 失败", t, exc_info=True)


@dataclass
class ControllerPair:
    upstream: HCIController
    downstream: HCIController
    _transports: tuple[Transport, Transport] = field(repr=False)

    async def close(self) -> None:
        # 逐个关闭;某个失败不影响其余(避免泄漏第二个 transport)。
        for t in self._transports:
            await _close_transport(t)


async def open_controller_pair(upstream: str, downstream: str) -> ControllerPair:
    up_t = await parse_transport_arg(upstream)
    down_t = await parse_transport_arg(downstream)
    up = HCIController(up_t)
    down = HCIController(down_t)
    opened: list[Transport] = []
    try:
        await up_t.open()
        opened.append(up_t)
        await down_t.open()
        opened.append(down_t)
        await asyncio.gather(up.initialize(), down.initialize())
    except Exception:
        # 部分失败:回滚已打开的 transport,避免泄漏 USB/UART 句柄。
        for t in reversed(opened):
            await _close_transport(t)
        raise
    return ControllerPair(upstream=up, downstream=down, _transports=(up_t, down_t))
