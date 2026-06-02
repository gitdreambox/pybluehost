"""PairingDelegate:Numeric Comparison 由测试者确认。

默认 AutoConfirmDelegate 在两侧都自动 yes(授权测试场景;数字不一致也接受,
见 spec §3.1)。CLI 的 --pairing numeric 用交互实现替换它。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class PairingDelegate(Protocol):
    async def confirm_numeric(self, side_name: str, value: int) -> bool: ...


class AutoConfirmDelegate:
    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        return True


async def _default_ask(prompt: str) -> str:
    # 在线程里读 stdin,避免阻塞事件循环
    return await asyncio.to_thread(input, prompt)


class InteractiveNumericDelegate:
    """Numeric Comparison:把 6 位数字打给测试者,在每一侧分别确认 y/n。

    授权测试场景两端都在测试者手上,即使两侧数字不同也可分别接受(见 spec §3.1)。
    """

    def __init__(self, ask: Callable[[str], Awaitable[str]] = _default_ask) -> None:
        self._ask = ask

    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        answer = await self._ask(
            f"[MITM] {side_name} 侧数字比较值 = {value:06d},确认配对? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes")
