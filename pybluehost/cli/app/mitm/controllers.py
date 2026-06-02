"""从两个 transport 字符串构造并初始化上下游 HCIController(仅 hci+transport)。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pybluehost.cli._transport import parse_transport_arg
from pybluehost.hci.controller import HCIController


@dataclass
class ControllerPair:
    upstream: HCIController
    downstream: HCIController
    _transports: tuple[object, object]

    async def close(self) -> None:
        for t in self._transports:
            close = getattr(t, "close", None)
            if close is not None:
                res = close()
                if asyncio.iscoroutine(res):
                    await res


async def open_controller_pair(upstream: str, downstream: str) -> ControllerPair:
    up_t = await parse_transport_arg(upstream)
    down_t = await parse_transport_arg(downstream)
    up = HCIController(up_t)
    down = HCIController(down_t)
    await up_t.open()
    await down_t.open()
    await asyncio.gather(up.initialize(), down.initialize())
    return ControllerPair(upstream=up, downstream=down, _transports=(up_t, down_t))
