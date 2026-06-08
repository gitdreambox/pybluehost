"""SnifferBackend abstraction — Ellisys / WPS plug in here."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pybluehost.core.trace import Direction


# Known H4 packet types (design spec §3.1). Anything outside is skipped by the sink.
KNOWN_H4_TYPES: frozenset[int] = frozenset({0x01, 0x02, 0x03, 0x04, 0x05})


class SnifferBackend(ABC):
    """Plug-in for VirtualSnifferSink. Lifecycle: start() → many inject() → stop()."""

    @abstractmethod
    async def start(self) -> None:
        """Launch / connect to analyzer software and perform minimum recording setup.

        One-time. May be slow (analyzer process spawn, port wait, IPC setup).
        Blocking parts must be offloaded to executor by the implementation.
        """

    @abstractmethod
    async def inject(
        self,
        h4_type: int,
        direction: Direction,
        payload: bytes,
        wall_clock: datetime,
    ) -> None:
        """Inject one HCI packet. `payload` does NOT include the H4 type byte.

        Must not block the asyncio event loop materially. UDP send is fine;
        ctypes calls go through run_in_executor.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Idempotent shutdown — release sockets / DLLs / subprocess handles."""
