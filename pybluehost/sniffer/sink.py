"""VirtualSnifferSink — a TraceSink that injects HCI into an analyzer backend."""
from __future__ import annotations

import logging

from pybluehost.core.trace import TraceEvent
from pybluehost.sniffer.backend import KNOWN_H4_TYPES, SnifferBackend

logger = logging.getLogger(__name__)

_HCI_LAYER = "hci"


class VirtualSnifferSink:
    """TraceSink that injects HCI events into an Ellisys / WPS analyzer.

    See design spec §5.2.

    - filters source_layer == "hci"
    - strips raw_bytes[0] (H4 type) and dispatches to the backend
    - unknown H4 types are skipped + warned once per type
    """

    def __init__(self, backend: SnifferBackend) -> None:
        self._backend = backend
        self._warned_unknown_h4: set[int] = set()

    async def on_trace(self, event: TraceEvent) -> None:
        if event.source_layer != _HCI_LAYER:
            return
        raw = event.raw_bytes
        if len(raw) < 1:
            return
        h4_type = raw[0]
        if h4_type not in KNOWN_H4_TYPES:
            if h4_type not in self._warned_unknown_h4:
                logger.warning(
                    "VirtualSnifferSink: skipping unknown H4 type 0x%02X", h4_type
                )
                self._warned_unknown_h4.add(h4_type)
            return
        await self._backend.inject(h4_type, event.direction, raw[1:], event.wall_clock)

    async def flush(self) -> None:
        # Injection is fire-and-forget; no buffered file to flush.
        pass

    async def close(self) -> None:
        await self._backend.stop()
