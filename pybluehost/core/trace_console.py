"""Live trace sink that writes structured HCI lines to a stream (default stderr).

Honors color via TTY auto-detect / NO_COLOR / FORCE_COLOR per the convention
shared with grep, git, bat. Filters by layer; falls back to a single
'undecoded' line when the trace event has no decoded payload.
"""
from __future__ import annotations

import os
import sys
from typing import IO

from pybluehost.core.trace import Direction, TraceEvent
from pybluehost.hci.format import format_hci_packet
from pybluehost.hci.packets import HCIPacket

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BRIGHT = "\x1b[1m"
_RED_BOLD = "\x1b[1;31m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_MAGENTA = "\x1b[35m"


class ConsoleSink:
    """Writes one HCI trace line per event to stream (default stderr)."""

    def __init__(
        self,
        *,
        stream: IO[str] | None = None,
        color: bool | None = None,
        layers: set[str] | None = None,
        level: str = "info",
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._color = self._resolve_color(color, self._stream)
        self._layers = layers
        self._level = level

    @staticmethod
    def _resolve_color(value: bool | None, stream: IO[str]) -> bool:
        if value is True:
            return True
        if value is False:
            return False
        # Auto: env vars first, then TTY check.
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        return bool(getattr(stream, "isatty", lambda: False)())

    async def on_trace(self, event: TraceEvent) -> None:
        if self._layers is not None and event.source_layer not in self._layers:
            return
        if event.source_layer != "hci":
            return  # Future: handle other layers; for now only HCI.
        line = self._render(event)
        if line:
            self._stream.write(line + "\n")
            self._stream.flush()

    def _render(self, event: TraceEvent) -> str:
        packet = event.decoded
        if not isinstance(packet, HCIPacket):
            preview = event.raw_bytes.hex()[:40]
            ellipsis = "..." if len(event.raw_bytes) > 20 else ""
            return f"{event.direction.name:<4} HCI <undecoded {preview}{ellipsis}>"
        try:
            line = format_hci_packet(
                packet,
                direction=event.direction,
                color=False,
                expand=(self._level == "debug"),
            )
        except Exception as exc:
            return f"<format error: {exc}> raw={event.raw_bytes.hex()[:40]}"
        if not self._color:
            return line
        return self._colorize(line, event.direction)

    @staticmethod
    def _colorize(line: str, direction: Direction) -> str:
        # Cyan/green for direction; keeps coloring simple at this stage.
        prefix = _CYAN if direction == Direction.DOWN else _GREEN
        return f"{prefix}{line}{_RESET}"

    async def flush(self) -> None:
        if hasattr(self._stream, "flush"):
            self._stream.flush()

    async def close(self) -> None:
        # Don't close stderr; only close streams the user explicitly handed us.
        pass
