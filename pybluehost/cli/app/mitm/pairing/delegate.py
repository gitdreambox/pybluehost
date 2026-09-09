"""PairingDelegate: Numeric Comparison confirmed by the tester.

The default AutoConfirmDelegate auto-answers yes on both sides (authorized-test scenario;
accepts even mismatched numbers, see spec §3.1). The CLI's --pairing numeric replaces it with
an interactive implementation.
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
    # Read stdin in a thread to avoid blocking the event loop
    return await asyncio.to_thread(input, prompt)


class InteractiveNumericDelegate:
    """Numeric Comparison: print the 6-digit number to the tester and confirm y/n on each
    side separately.

    In the authorized-test scenario both ends are in the tester's hands, so each side may be
    accepted even if the two numbers differ (see spec §3.1).
    """

    def __init__(self, ask: Callable[[str], Awaitable[str]] = _default_ask) -> None:
        self._ask = ask

    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        answer = await self._ask(
            f"[MITM] {side_name} 侧数字比较值 = {value:06d},确认配对? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes")
