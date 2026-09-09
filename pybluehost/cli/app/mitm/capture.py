"""Capture tap: write the relayed L2CAP PDUs into a btsnoop file (v1 only observes, no rewriting).

Reuses core.trace.BtsnoopSink (a pure btsnoop file writer, no protocol logic).
A future rewriting phase replaces this tap point with an InterceptionPipeline.

Performance: disk writes (BtsnoopSink does write+flush per packet) run in a background drain
task; ``on_pdu`` only enqueues (synchronous, instant) and **never blocks the forwarding hot
path**. AclRelay was also changed to "forward first, capture after", so capture latency is
entirely excluded from the phone↔target forwarding RTT.
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
    """No capture."""

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        return None

    async def close(self) -> None:
        return None


class BtsnoopCaptureTap:
    """Rewrap each relayed PDU as an HCI ACL record and write it to btsnoop (async in the
    background, never blocks forwarding)."""

    def __init__(self, path: str | Path) -> None:
        self._sink = BtsnoopSink(path)
        # Background disk write: on_pdu enqueues and returns; the _drain task writes serially
        # (preserving order), and disk flush doesn't block forwarding.
        self._queue: asyncio.Queue[Optional[TraceEvent]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closed = False

    async def on_pdu(self, direction: RelayDirection, handle: int, l2cap_pdu: bytes) -> None:
        if self._closed:
            return
        # l2cap_pdu is a complete L2CAP frame (the basic header: 2-byte length + 2-byte CID),
        # i.e. the output of encode_l2cap_basic() in AclRelay — written directly as the ACL
        # payload so Wireshark/Ellisys parse it correctly.
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
            source_layer="hci",  # must be ∈ BtsnoopSink._HCI_LAYERS, else the record is silently dropped
            direction=bt_dir,
            raw_bytes=acl.to_bytes(),
            decoded=None,
            connection_handle=handle,
            metadata={"mitm_direction": direction.value},
        )
        # Lazily start the background drain on first write (this must be inside relay's running loop).
        if self._task is None:
            self._task = asyncio.ensure_future(self._drain())
        self._queue.put_nowait(event)

    async def _drain(self) -> None:
        """Write queued events serially (preserving order); exit on the None sentinel."""
        while True:
            event = await self._queue.get()
            if event is None:
                return
            try:
                await self._sink.on_trace(event)
            except Exception:
                # A capture failure must not affect the relay (it happens after forwarding);
                # swallow and continue.
                pass

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            # Enqueue the sentinel so drain finishes all queued events before exiting,
            # ensuring everything is on disk when close() returns.
            self._queue.put_nowait(None)
            await self._task
            self._task = None
        await self._sink.close()
