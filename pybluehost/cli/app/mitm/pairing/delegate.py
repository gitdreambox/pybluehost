"""PairingDelegate:Numeric Comparison 由测试者确认。

默认 AutoConfirmDelegate 在两侧都自动 yes(授权测试场景;数字不一致也接受,
见 spec §3.1)。CLI 的 --pairing numeric 用交互实现替换它。
"""
from __future__ import annotations

from typing import Protocol


class PairingDelegate(Protocol):
    async def confirm_numeric(self, side_name: str, value: int) -> bool: ...


class AutoConfirmDelegate:
    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        return True
