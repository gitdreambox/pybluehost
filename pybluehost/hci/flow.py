"""HCI flow control: CommandFlowController and ACLFlowController.

CommandFlowController implements the HCI command credit-based flow control
(the controller tells the host how many commands it can accept via
num_hci_command_packets in Command Complete/Status events).

ACLFlowController manages the controller's ACL data buffer pool, acquired
per-packet before sending, returned via Number_Of_Completed_Packets events.
"""

from __future__ import annotations

import asyncio

from pybluehost.hci.packets import HCIEvent


class CommandFlowController:
    """Credit-based flow control for HCI commands.

    The controller starts with `initial_credits` (typically 1).
    Each sent command consumes one credit (acquire). Credits are replenished
    by Command Complete / Command Status events (release).
    """

    def __init__(self, initial_credits: int = 1) -> None:
        self._credits = asyncio.Semaphore(initial_credits)
        self._pending: dict[int, asyncio.Future[HCIEvent]] = {}

    async def acquire(self) -> None:
        """Wait until a command credit is available, then consume it."""
        await self._credits.acquire()

    def release(self, num: int = 1) -> None:
        """Return command credits (called when CC/CS event is received)."""
        for _ in range(num):
            self._credits.release()

    def register(self, opcode: int) -> asyncio.Future[HCIEvent]:
        """Register a pending command and return a Future for its response event."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[HCIEvent] = loop.create_future()
        self._pending[opcode] = fut
        return fut

    def resolve(self, opcode: int, event: HCIEvent) -> None:
        """Resolve the pending Future for a command opcode with the received event."""
        fut = self._pending.pop(opcode, None)
        if fut is not None and not fut.done():
            fut.set_result(event)


class ACLFlowController:
    """Buffer-based flow control for HCI ACL data packets.

    The controller advertises its ACL buffer count and size via
    Read_Buffer_Size. The host must not exceed the buffer count.
    Buffers are returned via Number_Of_Completed_Packets events.
    """

    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._buffer_size: int = 0

    def configure(self, num_buffers: int, buffer_size: int) -> None:
        """Configure flow control with the controller's buffer parameters."""
        self._sem = asyncio.Semaphore(num_buffers)
        self._buffer_size = buffer_size

    @property
    def available(self) -> int:
        """Number of available buffers."""
        if self._sem is None:
            return 0
        return self._sem._value

    @property
    def buffer_size(self) -> int:
        """Maximum ACL data payload size per buffer."""
        return self._buffer_size

    async def acquire(self, handle: int) -> None:
        """Wait for an available buffer before sending an ACL packet."""
        if self._sem is None:
            raise RuntimeError("ACLFlowController not configured")
        await self._sem.acquire()

    def on_num_completed(self, completed: dict[int, int]) -> None:
        """Return buffers based on Number_Of_Completed_Packets event."""
        if self._sem is None:
            return
        for _, count in completed.items():
            for _ in range(count):
                self._sem.release()

    def segment(self, data: bytes) -> list[bytes]:
        """Split data into segments fitting the controller's buffer size."""
        size = self._buffer_size or len(data)
        return [data[i : i + size] for i in range(0, len(data), size)]
