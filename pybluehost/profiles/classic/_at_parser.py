"""HFP-style AT command parser + formatter.

Parses one line at a time. The line-level buffer (`ATLineBuffer`) accepts
partial reads, splits on `\\r` or `\\n`, and yields stripped lines. Each
non-empty line is then dispatched via `parse_at_line` to one of three forms:

- `ATCommand` — starts with `AT...` (sent by HF to AG)
- `ATResponse` — paired terminator (`OK` / `ERROR`) OR a leading-`+` response
  to a specific command (e.g. `+BRSF: 871`)
- `ATUnsolicited` — AG-emitted indicator (RING, +CIEV, +CLIP, etc.)

Disambiguating `+BRSF:` (response) from `+CIEV:` (unsolicited) is contextual at
the SLC state machine level; the parser tags everything that's leading-`+` as
`ATResponse` and the state machine reclassifies as needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ATCommand:
    """A command sent from HF to AG."""
    name: str     # e.g. "+BRSF", "+CIND", "A" (for ATA), "+CHUP"
    kind: str     # 'action' | 'set' | 'read' | 'test'
    args: list[str] = field(default_factory=list)


@dataclass
class ATResponse:
    """A response from AG to HF — either a terminator (OK / ERROR) or a `+CMD: ...` line.

    The parser uses `ATResponse` as the default for leading-`+` lines; the SLC
    state machine reclassifies as `ATUnsolicited` for events not paired with a
    command (RING, +CIEV, +CLIP, etc.).
    """
    name: str
    args: list[str] = field(default_factory=list)
    is_terminator: bool = False


@dataclass
class ATUnsolicited:
    """An unsolicited indication from AG to HF."""
    name: str
    args: list[str] = field(default_factory=list)


_UNSOLICITED_NAMES = {"RING", "+CIEV", "+CLIP", "+CCWA", "+BVRA", "+BSIR", "+BCS"}


def parse_at_line(line: str) -> ATCommand | ATResponse | ATUnsolicited:
    """Parse one stripped AT line into the appropriate dataclass."""
    s = line.strip()
    if not s:
        raise ValueError("empty AT line")

    # Commands always start with AT (case-insensitive).
    if s[:2].upper() == "AT":
        body = s[2:]
        # Special-case bare ATA, ATD<num>;, ATH (no '+' prefix, no '=' or '?').
        if body and body[0] != "+":
            if body[0].upper() == "A" and len(body) == 1:
                return ATCommand(name="A", kind="action", args=[])
            # ATD/ATH and friends — Plan A.4 doesn't need them, but keep the door open.
            return ATCommand(name=body[0].upper(), kind="action", args=[body[1:]] if len(body) > 1 else [])
        # AT+CMD form
        rest = body[1:]   # drop '+'
        name = rest
        kind = "action"
        args: list[str] = []
        # Look for kind discriminators
        if "=" in rest:
            head, sep, tail = rest.partition("=")
            name = head
            if tail == "?":
                kind = "test"
            else:
                kind = "set"
                args = [a for a in tail.split(",")] if tail else []
        elif rest.endswith("?"):
            name = rest[:-1]
            kind = "read"
        else:
            name = rest
            kind = "action"
        return ATCommand(name=f"+{name}", kind=kind, args=args)

    # Terminators
    if s in ("OK", "ERROR"):
        return ATResponse(name=s, args=[], is_terminator=True)

    # Unsolicited well-known events
    if s == "RING":
        return ATUnsolicited(name="RING", args=[])

    # Leading-`+` lines: split into name + args.
    if s.startswith("+"):
        head, sep, tail = s.partition(":")
        name = head.strip()
        args = [a.strip() for a in tail.split(",")] if tail.strip() else []
        if name in _UNSOLICITED_NAMES:
            return ATUnsolicited(name=name, args=args)
        return ATResponse(name=name, args=args)

    # Fallback: treat as unsolicited so we don't lose data.
    return ATUnsolicited(name=s, args=[])


def format_at_command(cmd: ATCommand) -> str:
    """Serialise an ATCommand to bytes-string (CR terminator only, no LF)."""
    if cmd.name == "A" and cmd.kind == "action":
        return "ATA\r"
    base = cmd.name if cmd.name.startswith("+") else f"+{cmd.name}"
    if cmd.kind == "action":
        return f"AT{base}\r"
    if cmd.kind == "test":
        return f"AT{base}=?\r"
    if cmd.kind == "read":
        return f"AT{base}?\r"
    # set
    arg_str = ",".join(cmd.args)
    return f"AT{base}={arg_str}\r"


def format_at_response(resp: ATResponse) -> str:
    """Serialise an ATResponse, wrapped in <CR><LF>...<CR><LF>."""
    if resp.is_terminator:
        return f"\r\n{resp.name}\r\n"
    if not resp.args:
        return f"\r\n{resp.name}\r\n"
    return f"\r\n{resp.name}: {','.join(resp.args)}\r\n"


def format_unsolicited(msg: ATUnsolicited) -> str:
    if not msg.args:
        return f"\r\n{msg.name}\r\n"
    return f"\r\n{msg.name}: {','.join(msg.args)}\r\n"


class ATLineBuffer:
    """Accumulates partial reads; emits whole lines (split on `\\r` or `\\n`)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def drain(self) -> list[str]:
        """Return a list of complete lines (without terminators), keep any partial trailer."""
        text = self._buf.decode("ascii", errors="replace")
        # Normalise both \r\n and bare \r / \n.
        # We split on any of \r or \n, drop empties.
        out: list[str] = []
        cur = []
        for ch in text:
            if ch in ("\r", "\n"):
                if cur:
                    out.append("".join(cur))
                    cur.clear()
            else:
                cur.append(ch)
        # If we ended mid-line, preserve cur as partial trailer.
        partial = "".join(cur)
        self._buf = bytearray(partial.encode("ascii"))
        return out
