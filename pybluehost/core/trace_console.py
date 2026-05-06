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

    _DEFAULT_SUPPRESS = {"Number_Of_Completed_Packets"}

    def __init__(
        self,
        *,
        stream: IO[str] | None = None,
        color: bool | None = None,
        layers: set[str] | None = None,
        level: str = "info",
        include: set[str] | None = None,
        full_acl: bool = False,
        max_acl_payload: int = 24,
        adv_collapse_window: float = 5.0,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._color = self._resolve_color(color, self._stream)
        self._layers = layers
        self._level = level
        self._include = include or set()
        self._full_acl = full_acl
        self._max_acl_payload = max_acl_payload
        self._adv_collapse_window = adv_collapse_window
        self._recent_adv: dict[tuple[bytes, int], int] = {}
        self._last_adv_key: tuple[bytes, int] | None = None

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

    def _should_suppress(self, packet: object) -> bool:
        name = type(packet).__name__.replace("HCI_", "").replace("_Event", "")
        if name in self._include:
            return False
        return name in self._DEFAULT_SUPPRESS

    def _render(self, event: TraceEvent) -> str:
        packet = event.decoded
        if not isinstance(packet, HCIPacket):
            preview = event.raw_bytes.hex()[:40]
            ellipsis = "..." if len(event.raw_bytes) > 20 else ""
            return f"{event.direction.name:<4} HCI <undecoded {preview}{ellipsis}>"
        from pybluehost.hci.packets import HCI_LE_Meta_Event
        if isinstance(packet, HCI_LE_Meta_Event) and packet.subevent_code == 0x02:
            return self._render_le_adv_collapsed(event, packet)
        if self._should_suppress(packet):
            return ""
        from pybluehost.hci.packets import HCIACLData
        if isinstance(packet, HCIACLData):
            return self._render_acl(event, packet)
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

    def _render_le_adv_collapsed(self, event: TraceEvent, packet: "HCI_LE_Meta_Event") -> str:
        from pybluehost.hci.packets import parse_le_advertising_reports
        from pybluehost.hci.format_fields import format_address

        reports = parse_le_advertising_reports(packet.subevent_parameters)
        if not reports:
            return ""
        first = reports[0]
        key = (first.address, first.address_type)
        out_lines: list[str] = []

        # If address changed, flush any pending collapsed summary for the previous key.
        if self._last_adv_key is not None and self._last_adv_key != key:
            extra = self._recent_adv.get(self._last_adv_key, 0)
            if extra > 0:
                prev_addr_bytes, prev_type = self._last_adv_key
                addr_str = format_address(prev_addr_bytes, addr_type=prev_type)
                out_lines.append(f"  ... × {extra} more from {addr_str}")
            self._recent_adv.pop(self._last_adv_key, None)

        if key in self._recent_adv:
            self._recent_adv[key] += 1
            return "\n".join(out_lines) if out_lines else ""

        # First time seeing this key: print full line, start counter.
        self._recent_adv[key] = 0
        self._last_adv_key = key
        line = format_hci_packet(packet, direction=event.direction, color=False, expand=False)
        if self._color:
            line = self._colorize(line, event.direction)
        out_lines.append(line)
        return "\n".join(out_lines)

    def _render_acl(self, event: TraceEvent, packet: "HCIACLData") -> str:
        from pybluehost.hci.format import DIR_LABELS

        plen = len(packet.data)
        body = packet.data if self._full_acl else packet.data[: self._max_acl_payload]
        truncated = "" if (self._full_acl or plen <= self._max_acl_payload) else " ..."
        prefix = DIR_LABELS.get(event.direction, "  HCI")
        line = (
            f"{prefix} ACL  handle=0x{packet.handle:04X} len={plen} "
            f"data={body.hex(' ')}{truncated}"
        )
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
